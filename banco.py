"""Acesso ao banco SQLite: criação/migração das tabelas, usuário inicial,
POIs e regras de refinamento (com cache em memória)."""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

import seguranca

# Senha padrão antiga, que ficou pública no README/código. Usuários que ainda a
# usam são obrigados a trocá-la no próximo login.
SENHA_PADRAO_LEGADA = "Victor2005@"
ARQUIVO_SENHA_INICIAL = "senha_inicial_admin.txt"

# Lock para proteger o cache em memória de POIs/regras contra condições de corrida
# quando o Flask atende requisições concorrentes (threaded=True).
_CACHE_LOCK = threading.Lock()
_POIS_CACHE: list[dict[str, object]] | None = None
_REGRAS_CACHE: list[dict[str, Any]] | None = None
from config import data_dir


def get_connection():
    db_path = os.path.join(data_dir(), "poi_store.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # WAL reduz bloqueios de escrita/leitura concorrentes e acelera commits;
    # synchronous=NORMAL é seguro em modo WAL e evita fsyncs custosos a cada commit.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        colunas_existentes = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(pois)").fetchall()}
        if colunas_existentes and colunas_existentes.get("id", "").upper() != "TEXT":
            conn.execute("DROP TABLE IF EXISTS pois")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pois (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                tipo TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                cidade TEXT,
                estado TEXT,
                rodovia TEXT,
                raio_metros REAL,
                tempo_parado_seg INTEGER,
                velocidade_maxima_kmh REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pois_nome ON pois(nome COLLATE NOCASE);")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS regras_refinamento (
                id TEXT PRIMARY KEY,
                poi_id TEXT,
                categoria TEXT NOT NULL,
                descricao TEXT NOT NULL,
                ativa INTEGER DEFAULT 1,
                criada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (poi_id) REFERENCES pois(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_regras_ativa ON regras_refinamento(ativa);")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE COLLATE NOCASE,
                senha_hash TEXT NOT NULL,
                pode_cadastrar_usuarios INTEGER NOT NULL DEFAULT 0,
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        colunas_usuarios = {row[1] for row in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
        if "deve_trocar_senha" not in colunas_usuarios:
            conn.execute("ALTER TABLE usuarios ADD COLUMN deve_trocar_senha INTEGER NOT NULL DEFAULT 0")

        criar_admin_inicial_se_necessario(conn)
        forcar_troca_de_senha_padrao_legada(conn)
        conn.commit()
    finally:
        conn.close()


def criar_admin_inicial_se_necessario(conn: sqlite3.Connection) -> None:
    """Cria o primeiro administrador apenas quando não existe nenhum usuário.
    Nome e senha vêm de ADMIN_INICIAL_USUARIO / ADMIN_INICIAL_SENHA; sem senha
    definida, uma senha aleatória é gerada, exibida no console e gravada em
    `senha_inicial_admin.txt`. A troca é obrigatória no primeiro login."""
    existe_usuario = conn.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
    if existe_usuario:
        return

    nome = os.environ.get("ADMIN_INICIAL_USUARIO", "").strip() or "admin"
    senha = os.environ.get("ADMIN_INICIAL_SENHA", "")
    senha_gerada = not senha
    if senha_gerada:
        senha = seguranca.gerar_senha_temporaria()

    conn.execute(
        "INSERT INTO usuarios (id, nome, senha_hash, pode_cadastrar_usuarios, deve_trocar_senha) VALUES (?, ?, ?, 1, 1)",
        (uuid.uuid4().hex, nome, generate_password_hash(senha)),
    )

    if senha_gerada:
        caminho = os.path.join(data_dir(), ARQUIVO_SENHA_INICIAL)
        fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"Usuario: {nome}\nSenha temporaria: {senha}\n")
        print(
            "\n" + "=" * 60 +
            f"\n  Usuário administrador criado: {nome}"
            f"\n  Senha temporária: {senha}"
            f"\n  (também salva em {caminho})"
            "\n  Troque a senha no primeiro acesso."
            "\n" + "=" * 60 + "\n"
        )


def forcar_troca_de_senha_padrao_legada(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, senha_hash FROM usuarios WHERE deve_trocar_senha = 0 AND ativo = 1"
    ).fetchall()
    for row in rows:
        try:
            usa_padrao = check_password_hash(row["senha_hash"], SENHA_PADRAO_LEGADA)
        except (ValueError, TypeError):
            usa_padrao = False
        if usa_padrao:
            conn.execute("UPDATE usuarios SET deve_trocar_senha = 1 WHERE id = ?", (row["id"],))


def remover_arquivo_senha_inicial() -> None:
    caminho = os.path.join(data_dir(), ARQUIVO_SENHA_INICIAL)
    try:
        os.unlink(caminho)
    except OSError:
        pass


def get_regras_ativas() -> list[dict[str, Any]]:
    """Retorna as regras ativas, usando um cache em memória para evitar reabrir o
    SQLite em toda requisição (a rota `/` e o context_processor chamam isto com
    frequência). O cache é invalidado sempre que uma regra é criada/excluída."""
    global _REGRAS_CACHE
    with _CACHE_LOCK:
        if _REGRAS_CACHE is not None:
            return list(_REGRAS_CACHE)

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM regras_refinamento WHERE ativa = 1 ORDER BY criada_em DESC"
        ).fetchall()
        regras = [dict(row) for row in rows]
    finally:
        conn.close()

    with _CACHE_LOCK:
        _REGRAS_CACHE = regras
    return list(regras)


def invalidar_cache_regras() -> None:
    global _REGRAS_CACHE
    with _CACHE_LOCK:
        _REGRAS_CACHE = None


def invalidar_cache_pois() -> None:
    global _POIS_CACHE
    with _CACHE_LOCK:
        _POIS_CACHE = None


def adicionar_regra(descricao: str, categoria: str = "GERAL", poi_id: str | None = None) -> str:
    regra_id = uuid.uuid4().hex
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO regras_refinamento (id, poi_id, categoria, descricao, ativa)
            VALUES (?, ?, ?, ?, 1)
            """,
            (regra_id, poi_id, categoria, descricao),
        )
        conn.commit()
        return regra_id
    finally:
        conn.close()
        invalidar_cache_regras()


def get_saved_pois() -> list[dict[str, object]]:
    """Retorna os POIs salvos, usando um cache em memória. Com uma base de 16k+
    POIs, evitar reabrir o SQLite e re-serializar as linhas em toda requisição
    (rota `/` GET/POST + context_processor) é o ganho de performance mais direto."""
    global _POIS_CACHE
    with _CACHE_LOCK:
        if _POIS_CACHE is not None:
            return list(_POIS_CACHE)

    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM pois ORDER BY nome COLLATE NOCASE").fetchall()
        pois = [dict(row) for row in rows]
    finally:
        conn.close()

    with _CACHE_LOCK:
        _POIS_CACHE = pois
    return list(pois)


def save_saved_pois(pois: list[dict[str, object]]) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM pois")
        conn.executemany(
            """
            INSERT INTO pois (id, nome, tipo, latitude, longitude, cidade, estado, rodovia, raio_metros, tempo_parado_seg, velocidade_maxima_kmh)
            VALUES (:id, :nome, :tipo, :latitude, :longitude, :cidade, :estado, :rodovia, :raio_metros, :tempo_parado_seg, :velocidade_maxima_kmh)
            """,
            pois,
        )
        conn.commit()
    finally:
        conn.close()
    invalidar_cache_pois()


