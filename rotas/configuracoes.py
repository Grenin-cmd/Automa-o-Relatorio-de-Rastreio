"""Cadastros: Base de POIs, Regras de IA e Usuários."""
from __future__ import annotations

import sqlite3
import uuid

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

import seguranca

bp = Blueprint("configuracoes", __name__)
from banco import adicionar_regra, get_connection, get_saved_pois, invalidar_cache_pois, invalidar_cache_regras
from rotas.comum import login_required, usuario_atual


@bp.route("/pois")
@login_required
def pois():
    return render_template("pois.html", total_pois=len(get_saved_pois()))


@bp.route("/regras")
@login_required
def regras():
    return render_template("regras.html")


@bp.route("/configuracoes", methods=["GET", "POST"])
@login_required
def configuracoes():
    """Endereço antigo: GET vai para a Base de POIs; POST (formulários antigos) segue para Usuários."""
    if request.method == "GET":
        return redirect(url_for("configuracoes.pois"))
    return usuarios()


@bp.route("/usuarios", methods=["GET", "POST"])
@login_required
def usuarios():
    usuario = usuario_atual()
    if not usuario or not usuario["pode_cadastrar_usuarios"]:
        flash("Você não tem permissão para gerenciar usuários.", "warning")
        return redirect(url_for("configuracoes.pois"))
    if request.method == "POST":

        acao = request.form.get("acao")
        if acao == "criar_usuario":
            nome = request.form.get("nome", "").strip()
            senha = request.form.get("senha", "")
            pode_cadastrar = 1 if request.form.get("pode_cadastrar_usuarios") == "1" else 0
            erro_senha = seguranca.validar_nova_senha(senha) if senha else None
            if not nome or not senha:
                flash("Informe nome e senha para cadastrar o usuário.", "warning")
            elif erro_senha:
                flash(erro_senha, "warning")
            else:
                conn = get_connection()
                try:
                    # Senha definida pelo administrador é provisória: o usuário
                    # escolhe a própria no primeiro acesso.
                    conn.execute(
                        "INSERT INTO usuarios (id, nome, senha_hash, pode_cadastrar_usuarios, deve_trocar_senha) VALUES (?, ?, ?, ?, 1)",
                        (uuid.uuid4().hex, nome, generate_password_hash(senha), pode_cadastrar),
                    )
                    conn.commit()
                    flash(f"Usuário {nome} cadastrado com sucesso.", "success")
                except sqlite3.IntegrityError:
                    flash("Já existe um usuário com esse nome.", "warning")
                finally:
                    conn.close()
        elif acao == "alternar_permissao":
            usuario_id = request.form.get("usuario_id", "")
            if usuario_id == usuario["id"]:
                flash("A permissão do seu próprio perfil não pode ser removida.", "warning")
            else:
                conn = get_connection()
                try:
                    conn.execute(
                        "UPDATE usuarios SET pode_cadastrar_usuarios = CASE pode_cadastrar_usuarios WHEN 1 THEN 0 ELSE 1 END WHERE id = ?",
                        (usuario_id,),
                    )
                    conn.commit()
                    flash("Permissão de cadastro atualizada.", "success")
                finally:
                    conn.close()
        elif acao == "alternar_ativo":
            usuario_id = request.form.get("usuario_id", "")
            if usuario_id == usuario["id"]:
                flash("Você não pode desativar o seu próprio perfil.", "warning")
            else:
                conn = get_connection()
                try:
                    conn.execute(
                        "UPDATE usuarios SET ativo = CASE ativo WHEN 1 THEN 0 ELSE 1 END WHERE id = ?",
                        (usuario_id,),
                    )
                    conn.commit()
                    flash("Situação do usuário atualizada.", "success")
                finally:
                    conn.close()
        elif acao == "redefinir_senha":
            usuario_id = request.form.get("usuario_id", "")
            if usuario_id == usuario["id"]:
                flash("Use a opção 'Trocar minha senha' para alterar a sua.", "warning")
            else:
                senha_temporaria = seguranca.gerar_senha_temporaria()
                conn = get_connection()
                try:
                    cursor = conn.execute(
                        "UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 1 WHERE id = ?",
                        (generate_password_hash(senha_temporaria), usuario_id),
                    )
                    conn.commit()
                    if cursor.rowcount:
                        flash(
                            f"Senha temporária: {senha_temporaria} — repasse ao usuário; "
                            "ele deverá trocá-la no próximo acesso.",
                            "success",
                        )
                    else:
                        flash("Usuário não encontrado.", "warning")
                finally:
                    conn.close()
        return redirect(url_for("configuracoes.usuarios"))

    conn = get_connection()
    try:
        lista = [dict(row) for row in conn.execute(
            "SELECT id, nome, pode_cadastrar_usuarios, ativo FROM usuarios ORDER BY nome COLLATE NOCASE"
        ).fetchall()]
    finally:
        conn.close()
    return render_template("usuarios.html", usuarios=lista)


@bp.route("/excluir_regras", methods=["POST"])
@login_required
def excluir_regras():
    regra_ids = request.form.getlist("regra_ids")
    if not regra_ids:
        flash("Nenhuma regra selecionada para exclusão.", "warning")
        return redirect(url_for("configuracoes.regras"))

    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in regra_ids)
        conn.execute(f"DELETE FROM regras_refinamento WHERE id IN ({placeholders})", tuple(regra_ids))
        conn.commit()
        flash(f"{len(regra_ids)} regra(s) excluída(s) com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao excluir regras: {e}", "danger")
    finally:
        conn.close()
        invalidar_cache_regras()
    return redirect(url_for("configuracoes.regras"))


@bp.route("/excluir_pois", methods=["POST"])
@login_required
def excluir_pois():
    poi_ids = request.form.getlist("poi_ids")
    if not poi_ids:
        flash("Nenhum POI selecionado para exclusão.", "warning")
        return redirect(url_for("configuracoes.pois"))

    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in poi_ids)
        conn.execute(f"DELETE FROM pois WHERE id IN ({placeholders})", tuple(poi_ids))
        conn.commit()
        flash(f"{len(poi_ids)} POI(s) excluído(s) com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao excluir POIs: {e}", "danger")
    finally:
        conn.close()
        invalidar_cache_pois()
    return redirect(url_for("configuracoes.pois"))


@bp.route("/adicionar_regra_feedback", methods=["POST"])
@login_required
def adicionar_regra_feedback():
    descricao = request.form.get("descricao_regra", "").strip()
    categoria = request.form.get("categoria", "GERAL").strip()
    poi_id = request.form.get("poi_id") or None

    if not descricao:
        flash("A descrição da regra não pode estar vazia.", "warning")
    else:
        adicionar_regra(descricao, categoria, poi_id)
        flash("Instrução de IA salva com sucesso!", "success")

    return redirect(url_for("configuracoes.regras"))
