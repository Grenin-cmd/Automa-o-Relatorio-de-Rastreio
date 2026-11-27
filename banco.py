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
        _criar_tabela_locais(conn)
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


# ---------------------------------------------------------------------------
# Locais importantes (mensagem de saídas)
# ---------------------------------------------------------------------------
# Carga inicial tirada das mensagens manuais de 26/11 e 27/11/2026 (spec §4):
# (nome_exibicao, genero, tipo, aliases_ss, latitude, longitude, raio_m)
_LOCAIS_INICIAIS = [
    ("Matriz", "a", "MATRIZ", ["CECOTI MATRIZ", "CAMARA FRIA MATRIZ"], None, None, 250),
    ("CD de Contagem", "o", "CD", ["CECOTI CD CONTAGEM"], None, None, 150),
    ("CD de Uberlândia", "o", "CD", ["CECOTI CD UBERLANDIA"], None, None, 250),
    ("CD Supermercados BH em Contagem MG", "o", "CD", ["CD Mart Minas Contagem"], None, None, 300),
    ("CD Supermercado BH em Contagem MG", "o", "CD", ["CD SUPERMERCADO BH"], None, None, 250),
    ("Fontini em São Francisco de Paula MG", "a", "CD", ["FONTINI AGILMAX SFP"], None, None, 250),
    ("CEMA Central Mineira Atacadista em Ribeirão das Neves", "a", "CD", ["CEMA CENTRAL MINEIRA ATACADISTA"], None, None, 250),
    ("Cemil em Patos de Minas MG", "a", "CLIENTE", ["CEMIL"], None, None, 250),
    ("Posto Caxuxa na BR-262 em Luz MG", "o", "POSTO", ["POSTO CAXUXA LUZ BR-262 EM LUZ", "RESTAURANTE CAXUXA"], None, None, 250),
    ("Restaurante Ponto do Peixe em Nova Serrana MG", "o", "RESTAURANTE", ["RESTAURANTE PONTO DO PEIXE"], None, None, 250),
    ("Posto Dom Pedro na SP-065 em Atibaia SP", "o", "POSTO", [], -23.10011, -46.60962, 300),
]


def _criar_tabela_locais(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS locais_importantes (
            id TEXT PRIMARY KEY,
            nome_exibicao TEXT NOT NULL,
            genero TEXT NOT NULL CHECK (genero IN ('o', 'a')),
            tipo TEXT NOT NULL,
            aliases_ss TEXT NOT NULL DEFAULT '',
            latitude REAL,
            longitude REAL,
            raio_m REAL NOT NULL DEFAULT 250,
            cadastrado_na_ss INTEGER NOT NULL DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    if conn.execute("SELECT 1 FROM locais_importantes LIMIT 1").fetchone() is None:
        conn.executemany(
            "INSERT INTO locais_importantes (id, nome_exibicao, genero, tipo, aliases_ss, latitude, longitude, raio_m, cadastrado_na_ss)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            # Locais com alias já existem como POI na SS; os demais ainda precisam ser cadastrados lá.
            [(uuid.uuid4().hex, n, g, tp, "|".join(al), la, lo, r, 1 if al else 0) for n, g, tp, al, la, lo, r in _LOCAIS_INICIAIS],
        )


def listar_locais() -> list:
    from mensagem_saidas.locais import Local

    conn = get_connection()
    try:
        _criar_tabela_locais(conn)
        conn.commit()
        rows = conn.execute("SELECT * FROM locais_importantes ORDER BY nome_exibicao COLLATE NOCASE").fetchall()
    finally:
        conn.close()
    return [
        Local(
            id=r["id"], nome_exibicao=r["nome_exibicao"], genero=r["genero"], tipo=r["tipo"],
            aliases_ss=tuple(a for a in r["aliases_ss"].split("|") if a.strip()),
            latitude=r["latitude"], longitude=r["longitude"], raio_m=float(r["raio_m"]),
            cadastrado_na_ss=bool(r["cadastrado_na_ss"]),
        )
        for r in rows
    ]


def salvar_local(dados: dict[str, Any], local_id: str | None = None) -> str:
    """Cria (local_id=None) ou atualiza um local. `aliases_ss` é uma lista de nomes."""
    from mensagem_saidas.locais import TIPOS

    nome = str(dados.get("nome_exibicao", "")).strip()
    genero = dados.get("genero", "o")
    tipo = dados.get("tipo", "OUTRO")
    if not nome:
        raise ValueError("Informe o nome de exibição do local.")
    if genero not in ("o", "a") or tipo not in TIPOS:
        raise ValueError("Gênero ou tipo do local inválido.")
    aliases = "|".join(str(a).strip() for a in (dados.get("aliases_ss") or []) if str(a).strip())
    valores = (
        nome, genero, tipo, aliases,
        dados.get("latitude"), dados.get("longitude"),
        float(dados.get("raio_m") or 250),
    )
    conn = get_connection()
    try:
        _criar_tabela_locais(conn)
        if local_id:
            conn.execute(
                "UPDATE locais_importantes SET nome_exibicao=?, genero=?, tipo=?, aliases_ss=?, latitude=?, longitude=?, raio_m=? WHERE id=?",
                (*valores, local_id),
            )
        else:
            local_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO locais_importantes (nome_exibicao, genero, tipo, aliases_ss, latitude, longitude, raio_m, id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (*valores, local_id),
            )
        conn.commit()
    finally:
        conn.close()
    return local_id


def excluir_local(local_id: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM locais_importantes WHERE id = ?", (local_id,))
        conn.commit()
    finally:
        conn.close()


def marcar_cadastrado_na_ss(local_id: str, valor: bool) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE locais_importantes SET cadastrado_na_ss = ? WHERE id = ?", (1 if valor else 0, local_id))
        conn.commit()
    finally:
        conn.close()
