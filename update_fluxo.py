#!/usr/bin/env python3
"""
Atualiza o array FLUXO_DAILY no index.html com dados novos do dadosdemercado.com.br.
Roda via GitHub Actions todo dia útil de manhã.
"""

import re
import sys
import urllib.request
import urllib.error
import html as html_module

HTML_FILE = "index.html"
URL = "https://www.dadosdemercado.com.br/fluxo"

def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")

def parse_num(s):
    """Converte '−1.234,56 mi' → -1234.56"""
    s = s.strip()
    s = s.replace("\u2212", "-").replace("−", "-")  # unicode minus
    s = re.sub(r"\s*(mi|bi|milh[oõ]es|bilh[oõ]es)", "", s, flags=re.IGNORECASE)
    s = s.replace("R$", "").replace(" ", "")
    # Brazilian format: 1.234,56 → 1234.56
    if re.search(r"\d\.\d{3}[,]", s) or re.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

def parse_date(s):
    """DD/MM/YYYY → (d, iso)"""
    s = s.strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        dd, mm, yyyy = m.groups()
        return s, f"{yyyy}-{mm}-{dd}"
    return None, None

def scrape_rows(page_html):
    """Extrai linhas da tabela do dadosdemercado.com.br/fluxo"""
    # Procura pelo bloco da tabela
    table_match = re.search(
        r"<table[^>]*>(.*?)</table>",
        page_html,
        re.DOTALL | re.IGNORECASE
    )
    if not table_match:
        print("ERRO: tabela não encontrada na página", file=sys.stderr)
        return []

    table_html = table_match.group(1)

    # Extrai todas as <tr>
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)

    result = []
    for row in rows:
        # Extrai células <td>
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        if len(cells) < 5:
            continue
        # Remove tags HTML e decodifica entidades
        def clean(s):
            s = re.sub(r"<[^>]+>", "", s)
            return html_module.unescape(s).strip()

        cols = [clean(c) for c in cells]
        d_str, iso = parse_date(cols[0])
        if not d_str:
            continue

        result.append({
            "d":   d_str,
            "iso": iso,
            "est": parse_num(cols[1]) if len(cols) > 1 else 0.0,
            "ins": parse_num(cols[2]) if len(cols) > 2 else 0.0,
            "pf":  parse_num(cols[3]) if len(cols) > 3 else 0.0,
            "fin": parse_num(cols[4]) if len(cols) > 4 else 0.0,
            "out": parse_num(cols[5]) if len(cols) > 5 else 0.0,
        })

    return result

def read_existing_isos(html_content):
    """Extrai os iso dates já presentes no FLUXO_DAILY"""
    return set(re.findall(r"iso:'(\d{4}-\d{2}-\d{2})'", html_content))

def rows_to_js(rows):
    """Converte lista de dicts para linhas JS no formato do array"""
    lines = []
    for r in rows:
        lines.append(
            f"      {{d:'{r['d']}',iso:'{r['iso']}',"
            f"est:{r['est']:.2f},ins:{r['ins']:.2f},"
            f"pf:{r['pf']:.2f},fin:{r['fin']:.2f},out:{r['out']:.2f}}},"
        )
    return "\n".join(lines)

def update_html(html_content, new_rows):
    """Injeta as novas linhas antes do fechamento '];' do FLUXO_DAILY"""
    if not new_rows:
        return html_content, 0

    new_js = rows_to_js(new_rows)

    # Substitui o ]; final do array FLUXO_DAILY
    # Procura pelo padrão exato do arquivo
    pattern = r"(  const FLUXO_DAILY = \[.*?)(\n  \];)"
    replacement = r"\g<1>\n" + new_js + r"\g<2>"
    updated = re.sub(pattern, replacement, html_content, count=1, flags=re.DOTALL)

    if updated == html_content:
        print("AVISO: padrão FLUXO_DAILY não encontrado para substituição", file=sys.stderr)
        return html_content, 0

    return updated, len(new_rows)

def main():
    print(f"Buscando dados de {URL}...")
    try:
        page = fetch_page(URL)
    except urllib.error.URLError as e:
        print(f"ERRO ao buscar página: {e}", file=sys.stderr)
        sys.exit(1)

    scraped = scrape_rows(page)
    if not scraped:
        print("ERRO: nenhum dado extraído da página", file=sys.stderr)
        sys.exit(1)
    print(f"  → {len(scraped)} pregões encontrados na página")

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    existing = read_existing_isos(html_content)
    print(f"  → {len(existing)} pregões já no HTML")

    new_rows = [r for r in scraped if r["iso"] not in existing]
    new_rows.sort(key=lambda r: r["iso"])
    print(f"  → {len(new_rows)} pregões novos para adicionar")

    if not new_rows:
        print("Nada a atualizar. HTML já está com os dados mais recentes.")
        return

    updated_html, count = update_html(html_content, new_rows)

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(updated_html)

    print(f"✓ {count} pregão(ões) adicionado(s) ao index.html")
    for r in new_rows:
        print(f"    {r['d']}  EST:{r['est']:+.2f}  INS:{r['ins']:+.2f}  PF:{r['pf']:+.2f}")

if __name__ == "__main__":
    main()
