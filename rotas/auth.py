"""Login, logout e troca de senha."""
from __future__ import annotations


from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import seguranca

bp = Blueprint("auth", __name__)
from banco import SENHA_PADRAO_LEGADA, get_connection, remover_arquivo_senha_inicial
from rotas.comum import LIMITADOR_LOGIN, cleanup_cached_file, login_required, usuario_atual


@bp.route("/login", methods=["GET", "POST"])
def login():
    destino = seguranca.destino_seguro(request.args.get("proxima"), url_for("analise.index"))
    if usuario_atual() is not None:
        return redirect(destino)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "")
        chave_limite = f"{request.remote_addr}|{nome.lower()}"

        if LIMITADOR_LOGIN.bloqueado(chave_limite):
            flash("Muitas tentativas de login. Aguarde 15 minutos e tente novamente.", "danger")
            return render_template("login.html"), 429

        conn = get_connection()
        try:
            usuario = conn.execute(
                "SELECT id, nome, senha_hash FROM usuarios WHERE nome = ? COLLATE NOCASE AND ativo = 1",
                (nome,),
            ).fetchone()
        finally:
            conn.close()

        if usuario and check_password_hash(usuario["senha_hash"], senha):
            LIMITADOR_LOGIN.limpar(chave_limite)
            session.clear()
            session["usuario_id"] = usuario["id"]
            return redirect(destino)
        LIMITADOR_LOGIN.registrar_falha(chave_limite)
        flash("Nome ou senha inválidos.", "danger")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    cleanup_cached_file(incluir_auditoria=True)
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/trocar_senha", methods=["GET", "POST"])
@login_required
def trocar_senha():
    usuario = usuario_atual()
    assert usuario is not None
    obrigatoria = bool(usuario.get("deve_trocar_senha"))

    if request.method == "POST":
        senha_atual = request.form.get("senha_atual", "")
        nova_senha = request.form.get("nova_senha", "")
        confirmacao = request.form.get("confirmacao", "")

        conn = get_connection()
        try:
            row = conn.execute("SELECT senha_hash FROM usuarios WHERE id = ?", (usuario["id"],)).fetchone()
            erro = None
            if row is None or not check_password_hash(row["senha_hash"], senha_atual):
                erro = "Senha atual incorreta."
            elif nova_senha == senha_atual:
                erro = "A nova senha deve ser diferente da atual."
            elif nova_senha == SENHA_PADRAO_LEGADA:
                erro = "Essa senha é pública e não pode ser usada."
            else:
                erro = seguranca.validar_nova_senha(nova_senha, confirmacao)

            if erro:
                flash(erro, "danger")
            else:
                conn.execute(
                    "UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 0 WHERE id = ?",
                    (generate_password_hash(nova_senha), usuario["id"]),
                )
                conn.commit()
                remover_arquivo_senha_inicial()
                flash("Senha alterada com sucesso.", "success")
                return redirect(url_for("analise.index"))
        finally:
            conn.close()

    return render_template("trocar_senha.html", obrigatoria=obrigatoria)
