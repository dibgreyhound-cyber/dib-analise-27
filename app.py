            st.error("Não consegui detectar a distância. Preencha na barra lateral.")
            return
        today = parse_date(meta["r_date"])
        ctx = {"dist": dist, "today": today, "classe_n": grade_num(classe),
               "post_pick": [int(x) for x in re.findall(r"\d", pp_in)]}
        if classe and not ctx["classe_n"]:
            st.warning("Classe de hoje não reconhecida (use A1 a A11). O ajuste de classe foi ignorado.")
        ds = [analisar_galgo(d, ctx) for d in dogs]
        rank = finalizar(ds, ctx)
        ds.sort(key=lambda d: d["trap"])

        tab_a, tab_d = st.tabs(["📋 Análise", "🔎 Diagnóstico e dados brutos"])
        with tab_a:
            br = hora_br(hora)
            tit = f"{pista} {hora} (BR {br})" if br else pista
            st.markdown(f"### {tit} · Race {race} · {classe} · {int(dist)}m · POST PICK: {pp_in or '-'}")
            st.markdown("#### Planilha de Projeção")
            st.markdown(tabela_projecao(ds), unsafe_allow_html=True)
            st.markdown("**Classificação geral:** " + classificacao(rank))
            s1, s2, s3 = montar_avbs(rank, ctx)
            tabela_avb(s1, "1ª Planilha — AVB do Alvo 🎯 (Força ≥ 50)", ctx)
            tabela_avb(s2, "2ª Planilha — AVB Principal (Elite, Força ≥ 50)", ctx)
            tabela_avb(s3, "3ª Planilha — AVB Secundário (Elite, Força 40,0 a 49,9)", ctx)
            st.markdown("#### Observações")
            st.markdown(observacoes(rank))
        with tab_d:
            st.markdown("**Campos lidos do JSON** (se algum estiver 0, ajuste o `FIELD_MAP` no topo do código):")
            st.dataframe(diagnostico_campos(dogs), use_container_width=True, hide_index=True)
            st.markdown("**Chaves da primeira corrida do primeiro galgo (JSON bruto):**")
            first = meta["raw_first"]
            st.json(first.get("forms", [{}])[0] if first.get("forms") else first)
            linhas = [{"Galgo": d["name"], "Trap": d["trap"], **{k: r[k] for k in
                      ["date_str", "track", "dist", "grade", "split", "bends", "fin", "by", "wntm", "gng",
                       "weight", "remarks", "caltm"]}} for d in dogs for r in d["runs"]]
            st.dataframe(pd.DataFrame(linhas), use_container_width=True)


if __name__ == "__main__":
    main()
