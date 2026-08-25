from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import pandas as pd

from analisador_rastreio import RastreamentoAnalyzer, carregar_planilha


class AnalizadorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Analisador de Rastreio")
        self.root.geometry("760x560")
        self.root.resizable(False, False)

        self._criar_widgets()

    def _criar_widgets(self) -> None:
        frame = tk.Frame(self.root, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="Arquivo CSV ou Excel:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.arquivo_entry = tk.Entry(frame, width=64)
        self.arquivo_entry.grid(row=1, column=0, sticky="we", padx=(0, 8))
        tk.Button(frame, text="Selecionar arquivo", command=self._selecionar_arquivo).grid(row=1, column=1, sticky="e")

        tk.Label(frame, text="POIs (uma linha por item):", font=("Arial", 10, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", pady=(16, 0))
        self.pois_text = tk.Text(frame, width=88, height=8)
        self.pois_text.grid(row=3, column=0, columnspan=2, pady=(4, 0), sticky="we")

        exemplo = (
            "ClienteA:cliente:-23.5505:-46.6333:300:120:10\n"
            "PostoX:posto:-23.5600:-46.6400:250:120:10"
        )
        self.pois_text.insert("1.0", exemplo)

        tk.Label(frame, text="Relatório de saída:", font=("Arial", 10, "bold")).grid(row=4, column=0, columnspan=2, sticky="w", pady=(16, 0))
        self.output_text = scrolledtext.ScrolledText(frame, width=88, height=14, state="disabled")
        self.output_text.grid(row=5, column=0, columnspan=2, pady=(4, 0), sticky="we")

        botao_frame = tk.Frame(frame)
        botao_frame.grid(row=6, column=0, columnspan=2, pady=(16, 0), sticky="e")
        tk.Button(botao_frame, text="Executar análise", command=self._executar_analise, width=18).pack(side=tk.RIGHT)

        frame.grid_columnconfigure(0, weight=1)

    def _selecionar_arquivo(self) -> None:
        caminho = filedialog.askopenfilename(
            title="Selecione o arquivo CSV ou Excel",
            filetypes=[("CSV e Excel", "*.csv *.xlsx *.xls"), ("CSV", "*.csv"), ("Excel", "*.xlsx *.xls")],
        )
        if caminho:
            self.arquivo_entry.delete(0, tk.END)
            self.arquivo_entry.insert(0, caminho)

    def _executar_analise(self) -> None:
        caminho = self.arquivo_entry.get().strip().strip('"')
        if not caminho:
            messagebox.showwarning("Arquivo ausente", "Selecione um arquivo CSV ou Excel para continuar.")
            return

        try:
            df = carregar_planilha(caminho)
        except Exception as error:
            messagebox.showerror("Erro ao abrir arquivo", str(error))
            return

        pois = self._ler_pois()
        if not pois:
            messagebox.showwarning("POIs ausentes", "Informe pelo menos um POI no formato correto.")
            return

        analyzer = RastreamentoAnalyzer(pois=pois)
        try:
            relatorio = analyzer.gerar_relatorio(df)
            self._mostrar_relatorio(relatorio)
        except Exception as error:
            messagebox.showerror("Erro na análise", str(error))

    def _ler_pois(self) -> list[dict[str, object]]:
        texto = self.pois_text.get("1.0", tk.END).strip()
        pois = []
        for linha in texto.splitlines():
            if not linha.strip():
                continue
            partes = linha.split(":")
            if len(partes) != 7:
                continue
            nome, tipo, lat, lon, raio, tempo, velocidade = partes
            pois.append(
                {
                    "nome": nome,
                    "tipo": tipo,
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "raio_metros": float(raio),
                    "tempo_parado_seg": int(tempo),
                    "velocidade_maxima_kmh": float(velocidade),
                }
            )
        return pois

    def _mostrar_relatorio(self, texto: str) -> None:
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, texto)
        self.output_text.config(state="disabled")


def main() -> None:
    root = tk.Tk()
    app = AnalizadorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
