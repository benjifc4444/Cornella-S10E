#!/usr/bin/env python3
"""Actualiza index.html con el calendario, los resultados y la clasificación
del grupo 9 de Segona Divisió Benjamí S10 leyendo wanafutbol.com.

Uso:   python actualizar.py            (descarga la web y reescribe index.html)
       python actualizar.py --dry      (solo muestra lo que cambiaría)
Si algo no cuadra (la web cambia, faltan partidos, desaparecen resultados...)
el script se detiene SIN tocar index.html y termina con error.
"""
import socket
import argparse, datetime, html, json, re, sys, time, unicodedata, urllib.error, urllib.request, urllib.robotparser

URL = "https://wanafutbol.com/competicion/segona-divisio-benjami-s10/grup-9/calendario"
UA = "ActualizadorS10E/1.0 (uso personal, una peticion por semana)"
ANIO_INICIO = 2026          # la temporada 2026-27 empieza en 2026
ARCHIVO = "index.html"
NM = {"V": "Escola Futbol Vallvidrera A", "C": "Catalonia UB B", "H": "L’Hospitalet Centre Esports D",
      "O": "Horta UAT B", "P": "Penya Barc. Collblanc Sants A", "E": "Fundació UE Cornellà E",
      "S": "Sant Andreu UE D", "B": "Barceloneta CF A", "A": "Fundació Acadèmia F. L’Hospitalet B",
      "D": "Escola F. Àngel Pedraza B", "R": "Escola Futbol Premier Barcelona D", "M": "Martinenc FC C",
      "N": "Pª Barc. Barcino CE A", "T": "Escola Collblanc-Torrassa CE B", "L": "Les Corts de Barcelona Club Esp. A"}
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
         "sep": 9, "sept": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "des": 12, "gen": 1, "abr.": 4}
# Reconocimiento de equipos por palabras clave (el orden importa)
CLAVES = [("academia", "A"), ("torrassa", "T"), ("sant andreu", "S"), ("corts", "L"), ("premier", "R"),
          ("catalonia", "C"), ("martinenc", "M"), ("vallvidrera", "V"), ("pedraza", "D"),
          ("barceloneta", "B"), ("barcino", "N"), ("penya", "P"), ("sants", "P"), ("horta", "O"),
          ("hospitalet", "H"), ("cornella", "E")]


socket.setdefaulttimeout(30)


def fallo(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(1)


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[\"'’‘`“”]", "", s)).strip()


def codigo(nombre):
    n = norm(nombre)
    for clave, cod in CLAVES:
        if clave in n:
            return cod
    fallo(f"Equipo desconocido en la web: {nombre!r}")


def texto(fragmento):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragmento))).strip()


def descargar():
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request("https://wanafutbol.com/robots.txt", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
        if not rp.can_fetch(UA, URL):
            fallo("El robots.txt de wanafutbol.com no permite leer esta página de forma automática.")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            fallo(f"No se puede consultar el robots.txt de wanafutbol.com (HTTP {e.code}); no leo la web.")
        print(f"robots.txt no disponible (HTTP {e.code}); sigo con una sola lectura.")
    except Exception as e:  # noqa
        print(f"robots.txt no disponible ({e!r}); sigo con una sola lectura.")
    # Reintenta con calma si la web responde con un fallo temporal (503, 429, 500...).
    esperas = [15, 45, 90]
    ultimo = None
    for intento in range(len(esperas) + 1):
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept-Language": "es"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            ultimo = f"HTTP {e.code} {e.reason}"
            if e.code in (401, 403, 404, 410):
                fallo(f"La web rechaza la petición ({ultimo}). Parece que no permite lecturas automáticas; no insisto.")
            pausa = esperas[intento] if intento < len(esperas) else 0
            ra = e.headers.get("Retry-After") if e.headers else None
            if ra and ra.isdigit():
                pausa = min(max(pausa, int(ra)), 300)
        except Exception as e:  # noqa
            ultimo = repr(e)
            pausa = esperas[intento] if intento < len(esperas) else 0
        print(f"Intento {intento + 1} fallido ({ultimo}).", end=" ")
        if pausa:
            print(f"Reintento en {pausa} s...")
            time.sleep(pausa)
        else:
            print()
    fallo(f"No se pudo descargar la web tras varios intentos (último error: {ultimo}). "
          "Si se repite cada semana, la web bloquea las lecturas automáticas desde GitHub.")


RE_TOKEN = re.compile(r"(<h[1-4]\b[^>]*>.*?</h[1-4]>)|(<a\b(?=[^>]*href=[\"'][^\"']*/partido/)[^>]*>.*?</a>)", re.S | re.I)
RE_ATTR = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
RE_FECHA = re.compile(r"(?:lun|mar|mi[eé]|jue|vie|s[aá]b|dom)\.?,?\s+(\d{1,2})\s+([a-záéíóú]{3,5})\.?(?:\s+(\d{1,2}:\d{2}))?", re.I)
RE_PAR = re.compile(r"^(.*?)\s+vs\s+(.*?):\s*(.*)$")


def fecha_de(txt):
    m = RE_FECHA.search(txt)
    if not m:
        return None, None
    mes = MESES.get(norm(m.group(2)).rstrip("."))
    if not mes:
        return None, None
    return f"{int(m.group(1)):02d}/{mes:02d}", (m.group(3) or "").zfill(5) if m.group(3) else ""


def leer_web(pagina):
    """Devuelve {jornada: [ {h,a,fecha,hora,res,aj} ]} en el orden de la web."""
    tokens = list(RE_TOKEN.finditer(pagina))
    jornadas, vistos, jor = {}, set(), None
    for i, t in enumerate(tokens):
        if t.group(1):
            m = re.search(r"jornada\s+(\d+)", texto(t.group(1)), re.I)
            if m:
                jor = int(m.group(1))
            continue
        if jor is None:
            continue
        a = t.group(2)
        etiqueta = a[: a.find(">") + 1]
        attrs = {k.lower(): (v1 or v2) for k, v1, v2 in RE_ATTR.findall(etiqueta)}
        mid = re.search(r"/partido/(\d+)", attrs.get("href", ""))
        if not mid or mid.group(1) in vistos:
            continue
        vistos.add(mid.group(1))
        cuerpo = texto(a)
        par = RE_PAR.match(cuerpo) or RE_PAR.match(html.unescape(attrs.get("aria-label", "")))
        if not par:
            fallo(f"No se entiende el partido {mid.group(1)}: {cuerpo!r}")
        resto = par.group(3)
        fin = tokens[i + 1].start() if i + 1 < len(tokens) else len(pagina)
        detalle = texto(pagina[t.end():fin])[:200]
        marcador = re.match(r"^(\d+)\s*-\s*(\d+)\b", resto)
        fecha, hora = fecha_de(resto)
        if not fecha:
            fecha, hora = fecha_de(detalle)
        titulo = (attrs.get("title", "") + " " + attrs.get("aria-label", "")).lower()
        jornadas.setdefault(jor, []).append({
            "h": codigo(par.group(1)), "a": codigo(par.group(2)), "fecha": fecha, "hora": hora,
            "res": f"{marcador.group(1)}-{marcador.group(2)}" if marcador else "",
            "aj": (not marcador) and ("sin resultado" in titulo or "aplazado" in titulo or "ajornat" in titulo)})
    return jornadas


def cal_actual(src):
    m = re.search(r"var CAL=\[(.*?)\];", src, re.S)
    if not m:
        fallo("No encuentro 'var CAL' en index.html")
    previo, lineas = {}, re.findall(r'"([^"]*)"', m.group(1))
    for ln in lineas:
        for p in ln.split(" "):
            f = p.split(",")
            previo[(f[0][0], f[0][1])] = (f[1], f[2], f[3])
    return previo


def construir_cal(jornadas, previo):
    if sorted(jornadas) != list(range(1, 31)):
        fallo(f"Se esperaban 30 jornadas y la web da {len(jornadas)}")
    pares, lineas, resultados = {}, [], []
    for j in range(1, 31):
        ms = jornadas[j]
        if len(ms) != 7:
            fallo(f"La jornada {j} tiene {len(ms)} partidos y deberían ser 7")
        trozos = []
        for m in ms:
            h, a = m["h"], m["a"]
            pares[frozenset((h, a))] = pares.get(frozenset((h, a)), 0) + 1
            pf, ph, ps = previo.get((h, a), ("", "", ""))
            fecha = m["fecha"] or pf
            hora = m["hora"] if m["fecha"] else ph
            if not fecha:
                fallo(f"Falta la fecha del partido {NM[h]} - {NM[a]} (jornada {j})")
            if m["res"]:
                sc = m["res"]
            elif m["aj"]:
                sc = "aj"
            else:
                sc = ""
                if re.match(r"^\d+-\d+$", ps):
                    fallo(f"Desaparece el resultado de {NM[h]} - {NM[a]} (jornada {j}); no toco nada")
            trozos.append(f"{h}{a},{fecha},{hora},{sc}")
            if re.match(r"^\d+-\d+$", sc):
                resultados.append((j, h, a, fecha, hora, *map(int, sc.split("-"))))
        lineas.append(" ".join(trozos))
    if len(pares) != 105 or set(pares.values()) != {2}:
        fallo("Los enfrentamientos no cuadran (cada pareja debería jugar dos veces)")
    return lineas, resultados


def clave_tiempo(fecha, hora, jor):
    d, m = int(fecha[:2]), int(fecha[3:5])
    anio = ANIO_INICIO if m >= 8 else ANIO_INICIO + 1
    hh, mm = (int(hora[:2]), int(hora[3:5])) if hora else (0, 0)
    return (datetime.datetime(anio, m, d, hh, mm), jor)


def clasificacion(resultados):
    st = {c: {"pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0, "pts": 0, "hist": []} for c in NM}
    for j, h, a, f, hr, gh, ga in sorted(resultados, key=lambda r: clave_tiempo(r[3], r[4], r[0])):
        for eq, gf, gc in ((h, gh, ga), (a, ga, gh)):
            s = st[eq]
            s["pj"] += 1; s["gf"] += gf; s["gc"] += gc
            r = "G" if gf > gc else "E" if gf == gc else "P"
            s[{"G": "g", "E": "e", "P": "p"}[r]] += 1
            s["pts"] += 3 if r == "G" else 1 if r == "E" else 0
            s["hist"].append(r)

    def mini(grupo):
        pts = {c: 0 for c in grupo}; gd = {c: 0 for c in grupo}
        for j, h, a, f, hr, gh, ga in resultados:
            if h in grupo and a in grupo:
                gd[h] += gh - ga; gd[a] += ga - gh
                if gh > ga: pts[h] += 3
                elif gh < ga: pts[a] += 3
                else: pts[h] += 1; pts[a] += 1
        return pts, gd
    # Orden observado en la FCF: puntos, diferencia de goles total y, si siguen empatados,
    # enfrentamiento directo (puntos y diferencia) y goles a favor.
    orden = []
    claves = sorted({(s["pts"], s["gf"] - s["gc"]) for s in st.values()}, reverse=True)
    for pts, dg in claves:
        grupo = [c for c in NM if st[c]["pts"] == pts and st[c]["gf"] - st[c]["gc"] == dg]
        mp, mg = mini(grupo) if len(grupo) > 1 else ({c: 0 for c in grupo}, {c: 0 for c in grupo})
        grupo.sort(key=lambda c: (-mp[c], -mg[c], -st[c]["gf"], NM[c]))
        orden += grupo
    filas = []
    for c in orden:
        s = st[c]
        filas.append([NM[c], s["pj"], s["g"], s["e"], s["p"], s["gf"], s["gc"], "".join(s["hist"][-5:])])
    return filas


def aplicar(src, lineas, filas, clas_j):
    cal = "var CAL=[\n" + ",\n".join(json.dumps(l, ensure_ascii=False) for l in lineas) + "\n];"
    t = "var T=[" + ",\n".join(json.dumps(f, ensure_ascii=False) for f in filas) + "];"
    for patron, nuevo in ((r"var CAL=\[.*?\];", cal), (r"var T=\[.*?\];", t), (r"CLAS_J=\d+;", f"CLAS_J={clas_j};")):
        if not re.search(patron, src, re.S):
            fallo(f"No encuentro {patron!r} en index.html")
        src = re.sub(patron, lambda m, n=nuevo: n, src, count=1, flags=re.S)
    return src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--web", help="archivo HTML local en lugar de descargar (pruebas)")
    ap.add_argument("--archivo", default=ARCHIVO)
    a = ap.parse_args()
    pagina = open(a.web, encoding="utf-8").read() if a.web else descargar()
    src = open(a.archivo, encoding="utf-8").read()
    jornadas = leer_web(pagina)
    lineas, resultados = construir_cal(jornadas, cal_actual(src))
    filas = clasificacion(resultados)
    clas_j = max(r[0] for r in resultados) if resultados else 0
    nuevo = aplicar(src, lineas, filas, clas_j)
    jug = len(resultados)
    print(f"Jornadas: 30 | partidos con resultado: {jug} | clasificación tras la jornada {clas_j}")
    print("Líder:", filas[0][0], "-", filas[0][1], "PJ,", filas[0][2] * 3 + filas[0][3], "pts")
    if nuevo == src:
        print("Sin cambios.")
        return
    if a.dry:
        print("(--dry) Habría cambios en", a.archivo)
        return
    open(a.archivo, "w", encoding="utf-8").write(nuevo)
    print("index.html actualizado.")


if __name__ == "__main__":
    main()
