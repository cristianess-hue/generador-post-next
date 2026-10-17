import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import json
import io
import os
import time
from PIL import Image as PILImage, ImageDraw, ImageFont
from google import genai
from google.genai import types

st.set_page_config(page_title="Generador de Post Cuadrado", page_icon="🖼️", layout="wide")

API_KEY = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

LOGO_PATH = "logo_next.png"

ASESORES = {
    "Cristian Sosa": {
        "telefono": "6622057331",
        "foto": "cristian_sosa.jpg",
        "lema": "Tu nuevo comienzo empieza en la propiedad correcta."
    },
    "Claudia Castro": {
        "telefono": "6621387957",
        "foto": "claudia_castro.jpg",
        "lema": "Conectamos personas con los espacios que sueñan."
    }
}

ICONOS = {
    "recamaras": ["ico_cama.png", "1.png"],
    "banos": ["ico_bano.png", "2.png"],
    "pisos": ["ico_pisos.png", "3.png"],
    "estac": ["ico_auto.png", "4.png"],
    "construccion": ["ico_const.png", "5.png"],
    "terreno": ["ico_terreno.png", "6.png"]
}

# ==========================================
# CARGA LOCAL DE FUENTES DEL REPOSITORIO
# ==========================================

def cargar_fuente(size, bold=True):
    archivo = "fuente_bold.ttf" if bold else "fuente_regular.ttf"
    if os.path.exists(archivo):
        try:
            return ImageFont.truetype(archivo, size)
        except Exception:
            pass
    return ImageFont.load_default()

# ==========================================
# EXTRACCIÓN Y SCRAPING
# ==========================================

def extraer_datos_inmueble(url):
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "es-ES,es;q=0.9"
    }
    resp = session.get(url, headers=headers, timeout=20)
    resp.encoding = 'utf-8'
    soup = BeautifulSoup(resp.text, 'html.parser')

    og_title = ""
    meta_t = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if meta_t and meta_t.get("content"):
        og_title = meta_t["content"].strip()
    if not og_title:
        h1 = soup.find("h1")
        og_title = h1.get_text(strip=True) if h1 else ""

    og_desc = ""
    meta_d = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    if meta_d and meta_d.get("content"):
        og_desc = meta_d["content"].strip()

    for bloque in soup.find_all(lambda t: any(cl in str(t.get('class', '')).lower() or cl in str(t.get('id', '')).lower() 
                                            for cl in ['asesor', 'agente', 'agent', 'broker', 'perfil-asesor'])):
        bloque.extract()

    for s in soup(["script", "style", "noscript"]):
        s.extract()
    body_text = soup.get_text(separator="\n", strip=True)

    palabras_prohibidas = ["asesor", "agente", "agent", "staff", "perfil", "team", "logo", "avatar", "icon", "user"]
    imagenes = []

    meta_img = soup.find("meta", property="og:image")
    if meta_img and meta_img.get("content"):
        img_url = meta_img["content"]
        if "http" in img_url and not any(p in img_url.lower() for p in palabras_prohibidas):
            imagenes.append(img_url)

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        alt = (img.get("alt") or "").lower()
        if not src or any(p in src.lower() for p in palabras_prohibidas) or any(p in alt for p in palabras_prohibidas):
            continue
        if any(term in src.lower() for term in ["uploads", "listings", "propiedades", "images"]):
            full_src = re.sub(r'-[0-9]+x[0-9]+', '', src)
            if not full_src.startswith("http"):
                full_src = f"https://nextbr.mx{full_src}"
            if full_src not in imagenes:
                imagenes.append(full_src)

    matches_raw = re.findall(r'https?://[^\s"\']+\.(?:jpe?g|png|webp)', resp.text, re.IGNORECASE)
    for m in matches_raw:
        m_lower = m.lower()
        if ("listings" in m_lower or "uploads" in m_lower) and not any(p in m_lower for p in palabras_prohibidas):
            clean_m = re.sub(r'-[0-9]+x[0-9]+', '', m)
            if clean_m not in imagenes:
                imagenes.append(clean_m)

    return og_title, og_desc, body_text, imagenes

# ==========================================
# ESTRUCTURACIÓN CON IA
# ==========================================

def procesar_con_ia(url, og_title, og_desc, body_text, asesor_nombre, asesor_tel):
    client = genai.Client(api_key=API_KEY)
    prompt = f"""
    Eres un analista inmobiliario profesional. Extrae los datos exactos del inmueble y organízalos por secciones:
    URL: {url}
    Título: {og_title}
    Descripción: {og_desc}
    Texto: {body_text[:6000]}
    Asesor: {asesor_nombre} | Teléfono: {asesor_tel}

    Instrucciones estrictas:
    1. 'colonia': Nombre del fraccionamiento, plaza o colonia (ej: "Jardín Real", "Santa Fe", "Montecarlo").
    2. 'tipo_inmueble': "Casa", "Departamento", "Oficina", "Local Comercial", "Bodega" o "Terreno".
    3. 'operacion': "Renta" o "Venta".
    4. 'precio': El precio con formato SIN CENTAVOS (ej: "$14,000", "$3,100,000"). NUNCA pongas .00.
    5. 'moneda': "MXN" o "USD".
    6. 'recamaras': Número (ej: "3"). Si NO tiene, pon "".
    7. 'estacionamiento': Número de autos (ej: "2"). Si NO tiene, pon "".
    8. 'banos': Número (ej: "3" o "3.5"). Si NO tiene, pon "".
    9. 'pisos': Número de niveles o pisos (ej: "2"). Si NO tiene, pon "".
    10. 'construccion': Número de m² de construcción si se menciona (ej: "128"). Si NO tiene, pon "".
    11. 'terreno': Número de m² de terreno si se menciona (ej: "128"). Si NO tiene, pon "".
    12. 'copy_publicitario': Texto estructurado para WhatsApp con emojis respetando la información sin inventar detalles.
    13. 'texto_ficha_grafica': Resumen idéntico organizado por títulos en mayúsculas y viñetas (•) para la imagen.
        REGLA CRÍTICA DE REDACCIÓN:
        - NUNCA pongas las palabras "(si aplica)", "(si existe)", ni paréntesis explicativos en los títulos.
        - Los títulos válidos son solo:
          DISTRIBUCIÓN Y ESPACIOS
          EQUIPAMIENTO
          SERVICIOS INCLUIDOS
          ÁREA COMÚN / PRIVADA
          ESTATUS LEGAL
        - Si un inmueble no incluye servicios o no tiene áreas comunes, simplemente OMITE ese bloque por completo.

    Devuelve un JSON estrictamente válido:
    {{
      "colonia": "Jardín Real",
      "tipo_inmueble": "Casa",
      "operacion": "Renta",
      "precio": "$14,000",
      "moneda": "MXN",
      "recamaras": "3",
      "estacionamiento": "2",
      "banos": "3.5",
      "pisos": "2",
      "construccion": "128",
      "terreno": "128",
      "copy_publicitario": "...",
      "texto_ficha_grafica": "..."
    }}
    """
    modelos = ['gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-3.5-flash-lite']
    for mod in modelos:
        try:
            res = client.models.generate_content(
                model=mod,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(res.text)
            
            # Limpieza forzada de "(si aplica)" tanto en el texto gráfico como en el copy
            if "texto_ficha_grafica" in data:
                data["texto_ficha_grafica"] = re.sub(r'\s*\((?:si\s+aplica|si\s+existe)\)', '', data["texto_ficha_grafica"], flags=re.IGNORECASE)
            if "copy_publicitario" in data:
                data["copy_publicitario"] = re.sub(r'\s*\((?:si\s+aplica|si\s+existe)\)', '', data["copy_publicitario"], flags=re.IGNORECASE)

            return data
        except Exception:
            time.sleep(1)
            continue
    raise Exception("Modelos saturados temporalmente.")

# ==========================================
# DESCARGA Y RECORTE PROPORCIONAL
# ==========================================

def descargar_y_recortar(url, target_w, target_h):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=12)
    if r.status_code != 200:
        return None
    img = PILImage.open(io.BytesIO(r.content)).convert("RGB")
    
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        offset = (img.width - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        offset = (img.height - new_h) // 2
        img = img.crop((0, offset, img.width, offset + new_h))

    return img.resize((target_w, target_h), PILImage.Resampling.LANCZOS)

def pegar_icono(lienzo, clave_icono, x_centro, y_centro, max_size=52):
    nombres_posibles = ICONOS.get(clave_icono, [])
    ruta_encontrada = None
    for nom in nombres_posibles:
        if os.path.exists(nom):
            ruta_encontrada = nom
            break

    if ruta_encontrada:
        try:
            ico = PILImage.open(ruta_encontrada).convert("RGBA")
            ico.thumbnail((max_size, max_size), PILImage.Resampling.LANCZOS)
            px = int(x_centro - (ico.width / 2))
            py = int(y_centro - (ico.height / 2))
            lienzo.paste(ico, (px, py), mask=ico)
        except Exception:
            pass

# ==========================================
# BASE COMÚN GRÁFICA
# ==========================================

def renderizar_base_flyer(datos, asesor_nombre, asesor_datos):
    ancho, alto = 1200, 1200
    lienzo = PILImage.new("RGB", (ancho, alto), (255, 255, 255))
    draw = ImageDraw.Draw(lienzo)

    font_colonia = cargar_fuente(50, bold=True)
    font_tipo = cargar_fuente(34, bold=True)
    font_operacion = cargar_fuente(42, bold=True)
    font_moneda = cargar_fuente(22, bold=True)
    
    font_datos_num = cargar_fuente(38, bold=True)
    font_datos_lbl = cargar_fuente(18, bold=True)
    
    font_pie_nombre = cargar_fuente(42, bold=True)
    font_pie_tel = cargar_fuente(40, bold=True)
    font_pie_cargo = cargar_fuente(22, bold=False)
    font_pie_lema = cargar_fuente(20, bold=False)

    ROJO_NEXT = (227, 6, 19)
    GRIS_OSCURO = (30, 41, 59)
    GRIS_LINEA = (226, 232, 240)

    # 1. TÍTULO CENTRADO
    cx_zona_der = 750
    colonia = str(datos.get("colonia", "PROPIEDAD")).upper().strip()
    draw.text((cx_zona_der, 50), colonia, fill=ROJO_NEXT, font=font_colonia, anchor="mm")

    # 2. ESPECIFICACIONES VÁLIDAS
    caracteristicas_validas = []

    def es_valido(v):
        s = str(v).strip()
        return s and s not in ["-", "0", "None", "null"]

    if es_valido(datos.get("recamaras")):
        caracteristicas_validas.append({"clave": "recamaras", "valor": str(datos.get("recamaras")).strip(), "label": "RECAMARAS"})
    if es_valido(datos.get("estacionamiento")):
        caracteristicas_validas.append({"clave": "estac", "valor": str(datos.get("estacionamiento")).strip(), "label": "ESTAC."})
    if es_valido(datos.get("banos")):
        caracteristicas_validas.append({"clave": "banos", "valor": str(datos.get("banos")).strip(), "label": "BAÑOS"})
    if es_valido(datos.get("pisos")):
        caracteristicas_validas.append({"clave": "pisos", "valor": str(datos.get("pisos")).strip(), "label": "PISOS"})
    if es_valido(datos.get("construccion")):
        caracteristicas_validas.append({"clave": "construccion", "valor": str(datos.get("construccion")).strip(), "label": "CONST. m2"})
    if es_valido(datos.get("terreno")):
        caracteristicas_validas.append({"clave": "terreno", "valor": str(datos.get("terreno")).strip(), "label": "TERRENO m2"})

    filas_specs = []
    idx_spec = 0
    while idx_spec < len(caracteristicas_validas):
        if idx_spec + 1 < len(caracteristicas_validas):
            filas_specs.append([caracteristicas_validas[idx_spec], caracteristicas_validas[idx_spec + 1]])
            idx_spec += 2
        else:
            filas_specs.append([caracteristicas_validas[idx_spec]])
            idx_spec += 1

    cx_izq = 165
    num_filas = len(filas_specs)

    if num_filas >= 3:
        y_cursor = 140
        gap_fila = 55
        gap_sep = 115
    elif num_filas == 2:
        y_cursor = 160
        gap_fila = 70
        gap_sep = 145
    elif num_filas == 1:
        y_cursor = 190
        gap_fila = 85
        gap_sep = 165
    else:
        y_cursor = 240
        gap_fila = 0
        gap_sep = 0

    draw.text((cx_izq, y_cursor - 60), datos.get("tipo_inmueble", "CASA").upper(), fill=GRIS_OSCURO, font=font_tipo, anchor="mm")
    draw.text((cx_izq, y_cursor - 10), datos.get("operacion", "Renta"), fill=ROJO_NEXT, font=font_operacion, anchor="mm")

    # PRECIO
    precio_raw = str(datos.get("precio", "$0")).strip()
    precio_limpio = re.sub(r'\.00$', '', precio_raw)

    size_precio = 52
    font_precio = cargar_fuente(size_precio, bold=True)
    max_ancho_precio = 270

    while size_precio > 24:
        bbox = draw.textbbox((0, 0), precio_limpio, font=font_precio)
        ancho_texto = bbox[2] - bbox[0]
        if ancho_texto <= max_ancho_precio:
            break
        size_precio -= 2
        font_precio = cargar_fuente(size_precio, bold=True)

    draw.text((cx_izq, y_cursor + 50), precio_limpio, fill=GRIS_OSCURO, font=font_precio, anchor="mm")
    draw.text((cx_izq, y_cursor + 90), datos.get("moneda", "MXN"), fill=GRIS_OSCURO, font=font_moneda, anchor="mm")

    y_linea_base = y_cursor + 120
    draw.line([(30, y_linea_base), (300, y_linea_base)], fill=GRIS_LINEA, width=2)

    y_actual = y_linea_base
    for fila in filas_specs:
        y_fila_texto = y_actual + gap_fila
        if len(fila) == 2:
            item_a, item_b = fila[0], fila[1]
            draw.text((cx_izq - 65, y_fila_texto), item_a["valor"], fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
            draw.text((cx_izq - 65, y_fila_texto + 28), item_a["label"], fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
            pegar_icono(lienzo, item_a["clave"], cx_izq - 65, y_fila_texto + 70, max_size=52)

            draw.text((cx_izq + 65, y_fila_texto), item_b["valor"], fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
            draw.text((cx_izq + 65, y_fila_texto + 28), item_b["label"], fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
            pegar_icono(lienzo, item_b["clave"], cx_izq + 65, y_fila_texto + 70, max_size=52)
        else:
            item_u = fila[0]
            draw.text((cx_izq, y_fila_texto), item_u["valor"], fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
            draw.text((cx_izq, y_fila_texto + 28), item_u["label"], fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
            pegar_icono(lienzo, item_u["clave"], cx_izq, y_fila_texto + 70, max_size=52)

        y_actual = y_fila_texto + gap_sep
        draw.line([(30, y_actual), (300, y_actual)], fill=GRIS_LINEA, width=2)

    # 3. TARJETA INFERIOR ASESOR
    foto_ruta = asesor_datos.get("foto", "")
    if foto_ruta and os.path.exists(foto_ruta):
        try:
            foto_asesor = PILImage.open(foto_ruta).convert("RGBA")
            foto_asesor.thumbnail((210, 240), PILImage.Resampling.LANCZOS)
            draw.rounded_rectangle([(30, 910), (245, 1165)], radius=16, outline=(254, 205, 211), width=4)
            px = int(30 + (215 - foto_asesor.width) / 2)
            py = int(910 + (255 - foto_asesor.height) / 2)
            lienzo.paste(foto_asesor, (px, py), mask=foto_asesor if "A" in foto_asesor.getbands() else None)
        except Exception:
            pass

    # 4. CONTACTO CENTRAL INFERIOR
    cx_contacto = 560
    draw.text((cx_contacto, 975), asesor_nombre.upper(), fill=ROJO_NEXT, font=font_pie_nombre, anchor="mm")
    draw.text((cx_contacto, 1025), asesor_datos.get("telefono", ""), fill=(51, 65, 85), font=font_pie_tel, anchor="mm")
    draw.text((cx_contacto, 1070), "ASESOR INMOBILIARIO ASOCIADO", fill=(100, 116, 139), font=font_pie_cargo, anchor="mm")
    draw.text((cx_contacto, 1110), f'"{asesor_datos.get("lema", "")}"', fill=(148, 163, 184), font=font_pie_lema, anchor="mm")

    # 5. LOGO NEXT
    if os.path.exists(LOGO_PATH):
        try:
            logo = PILImage.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((320, 150), PILImage.Resampling.LANCZOS)
            lienzo.paste(logo, (840, 980), mask=logo if "A" in logo.getbands() else None)
        except Exception:
            pass

    return lienzo

# ==========================================
# GENERADOR 1: FLYER DE PORTADA
# ==========================================

def generar_flyer_portada(datos, urls_4_fotos, asesor_nombre, asesor_datos):
    lienzo = renderizar_base_flyer(datos, asesor_nombre, asesor_datos)

    x_col1 = 330
    x_col2 = 765
    y_fila1 = 118
    y_fila2 = 508
    foto_w, foto_h = 405, 365

    posiciones = [
        (x_col1, y_fila1),
        (x_col2, y_fila1),
        (x_col1, y_fila2),
        (x_col2, y_fila2)
    ]

    for idx, url in enumerate(urls_4_fotos):
        if idx < 4 and url:
            img_rec = descargar_y_recortar(url, foto_w, foto_h)
            if img_rec:
                lienzo.paste(img_rec, posiciones[idx])

    buf = io.BytesIO()
    lienzo.save(buf, format="JPEG", quality=100, subsampling=0)
    buf.seek(0)
    return buf.getvalue()

# ==========================================
# GENERADOR 2: FICHA TÉCNICA ESTRUCTURADA
# ==========================================

def generar_flyer_ficha(datos, asesor_nombre, asesor_datos):
    lienzo = renderizar_base_flyer(datos, asesor_nombre, asesor_datos)
    draw = ImageDraw.Draw(lienzo)

    x_ini, y_ini = 330, 118
    x_fin, y_fin = 1170, 873
    ancho_panel = x_fin - x_ini

    draw.rounded_rectangle([(x_ini, y_ini), (x_fin, y_fin)], radius=16, fill=(248, 250, 252), outline=(226, 232, 240), width=2)
    
    # Encabezado del contenedor
    draw.rounded_rectangle([(x_ini, y_ini), (x_fin, y_ini + 58)], radius=16, fill=(241, 245, 249))
    draw.rectangle([(x_ini, y_ini + 30), (x_fin, y_ini + 58)], fill=(241, 245, 249))
    draw.line([(x_ini, y_ini + 58), (x_fin, y_ini + 58)], fill=(226, 232, 240), width=2)

    font_header_ficha = cargar_fuente(25, bold=True)
    draw.text((x_ini + 25, y_ini + 29), "FICHA TÉCNICA Y DETALLES DEL INMUEBLE", fill=(30, 41, 59), font=font_header_ficha, anchor="lm")

    font_seccion = cargar_fuente(23, bold=True)
    font_cuerpo = cargar_fuente(21, bold=False)

    texto_ficha = datos.get("texto_ficha_grafica", "")
    lineas_raw = [l.strip() for l in texto_ficha.split("\n") if l.strip()]

    y_pos = y_ini + 85
    max_w_texto = ancho_panel - 70

    for linea in lineas_raw:
        # Limpieza de seguridad por si escapa un paréntesis de condición
        linea = re.sub(r'\s*\((?:si\s+aplica|si\s+existe)\)', '', linea, flags=re.IGNORECASE).strip()
        if not linea:
            continue

        es_subtitulo = not linea.startswith("•") and not linea.startswith("-") and (linea.isupper() or any(s in linea.lower() for s in ["distribución", "equipamiento", "servicios", "área común", "estatus", "amenidades"]))

        if es_subtitulo:
            y_pos += 12
            fuente_actual = font_seccion
            color_actual = (227, 6, 19)
            x_offset = x_ini + 30
        else:
            fuente_actual = font_cuerpo
            color_actual = (51, 65, 85)
            x_offset = x_ini + 42

        palabras = linea.split(" ")
        linea_parcial = ""

        for pal in palabras:
            prueba = f"{linea_parcial} {pal}".strip()
            bbox = draw.textbbox((0, 0), prueba, font=fuente_actual)
            if (bbox[2] - bbox[0]) <= max_w_texto:
                linea_parcial = prueba
            else:
                if y_pos < y_fin - 30:
                    draw.text((x_offset, y_pos), linea_parcial, fill=color_actual, font=fuente_actual)
                    y_pos += 30
                linea_parcial = pal

        if linea_parcial and y_pos < y_fin - 30:
            draw.text((x_offset, y_pos), linea_parcial, fill=color_actual, font=fuente_actual)
            y_pos += 34 if es_subtitulo else 30

    buf = io.BytesIO()
    lienzo.save(buf, format="JPEG", quality=100, subsampling=0)
    buf.seek(0)
    return buf.getvalue()

# ==========================================
# INICIALIZACIÓN DE ESTADO
# ==========================================

if "datos_extraidos" not in st.session_state:
    st.session_state.datos_extraidos = None
if "fotos_extraidas" not in st.session_state:
    st.session_state.fotos_extraidas = []
if "img_portada" not in st.session_state:
    st.session_state.img_portada = None
if "img_ficha" not in st.session_state:
    st.session_state.img_ficha = None
if "nombre_portada" not in st.session_state:
    st.session_state.nombre_portada = ""
if "nombre_ficha" not in st.session_state:
    st.session_state.nombre_ficha = ""
if "copy_publicitario" not in st.session_state:
    st.session_state.copy_publicitario = ""

# ==========================================
# INTERFAZ STREAMLIT
# ==========================================

st.title("🖼️ Generador Dual de Posts Cuadrados (1200x1200)")
st.write("Genera simultáneamente la **Foto 1 (Portada con fotos)** y la **Foto 2 (Ficha Técnica Gráfica)**:")

col_url, col_as = st.columns([2, 1])
with col_url:
    url_input = st.text_input("Enlace de la propiedad:", placeholder="https://nextbr.mx/propiedades/...")
with col_as:
    asesor_seleccionado = st.selectbox("Selecciona Asesor:", options=list(ASESORES.keys()), index=0)

info_asesor = ASESORES[asesor_seleccionado]
st.caption(f"📲 Contacto: **{info_asesor['telefono']}** | Lema: *\"{info_asesor['lema']}\"*")

if st.button("🔍 Extraer Propiedad y Fotos", type="primary"):
    if not url_input.strip().startswith("http"):
        st.error("Por favor ingresa un enlace válido de Next Bienes Raíces.")
    elif not API_KEY:
        st.error("Falta configurar GEMINI_API_KEY en Secrets.")
    else:
        with st.spinner("Analizando portal, extrayendo fotos y estructurando datos..."):
            try:
                og_t, og_d, b_txt, fotos = extraer_datos_inmueble(url_input.strip())
                datos = procesar_con_ia(url_input.strip(), og_t, og_d, b_txt, asesor_seleccionado, info_asesor['telefono'])
                
                st.session_state.datos_extraidos = datos
                st.session_state.fotos_extraidas = fotos
                st.session_state.copy_publicitario = datos.get("copy_publicitario", "")
                st.session_state.img_portada = None
                st.session_state.img_ficha = None
                
                st.success(f"¡Propiedad analizada con éxito! ({datos.get('tipo_inmueble', '')} en {datos.get('colonia', '')} - {datos.get('precio', '')})")
            except Exception as e:
                st.error(f"Error al analizar el portal: {e}")

# ==========================================
# SELECCIÓN DE FOTOS Y GENERACIÓN DUAL
# ==========================================
if st.session_state.datos_extraidos and st.session_state.fotos_extraidas:
    st.markdown("---")
    st.subheader("📸 Selecciona las 4 fotos para la Portada:")

    fotos = st.session_state.fotos_extraidas
    num_cols = 3
    for fila_idx in range(0, len(fotos), num_cols):
        bloque_fotos = fotos[fila_idx : fila_idx + num_cols]
        cols_fila = st.columns(num_cols)
        for c_idx, f_url in enumerate(bloque_fotos):
            numero_foto = fila_idx + c_idx + 1
            with cols_fila[c_idx]:
                st.image(f_url, caption=f"Foto #{numero_foto}", use_container_width=True)

    opciones = list(range(1, len(fotos) + 1))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        f1_idx = st.selectbox("1. Principal (Arr. Izq):", opciones, index=0)
    with c2:
        f2_idx = st.selectbox("2. Detalle (Arr. Der):", opciones, index=min(1, len(fotos)-1))
    with c3:
        f3_idx = st.selectbox("3. Interior (Abj. Izq):", opciones, index=min(2, len(fotos)-1))
    with c4:
        f4_idx = st.selectbox("4. Espacio (Abj. Der):", opciones, index=min(3, len(fotos)-1))

    st.markdown("---")
    
    if st.button("✨ Generar Ambos Flyers (Portada + Ficha Técnica)", type="primary", use_container_width=True):
        urls_seleccionadas = [
            fotos[f1_idx - 1],
            fotos[f2_idx - 1],
            fotos[f3_idx - 1],
            fotos[f4_idx - 1]
        ]
        with st.spinner("Componiendo ambas imágenes en ultra alta resolución..."):
            datos = st.session_state.datos_extraidos
            
            img_p = generar_flyer_portada(datos, urls_seleccionadas, asesor_seleccionado, info_asesor)
            img_f = generar_flyer_ficha(datos, asesor_seleccionado, info_asesor)
            
            tipo_limpio = str(datos.get('tipo_inmueble', 'Inmueble')).strip().capitalize()
            colonia_limpia = str(datos.get('colonia', 'Propiedad')).strip().title()
            precio_limpio = re.sub(r'\.00$', '', str(datos.get('precio', ''))).strip()

            base_nom = f"{tipo_limpio} en {colonia_limpia} {precio_limpio}"
            base_limpio = re.sub(r'[\\/*?:\"<>|]', '', base_nom).strip()

            st.session_state.img_portada = img_p
            st.session_state.nombre_portada = f"{base_limpio} - Portada.jpg"

            st.session_state.img_ficha = img_f
            st.session_state.nombre_ficha = f"{base_limpio} - Ficha Tecnica.jpg"

# ==========================================
# RESULTADOS PERSISTENTES (AMBAS IMÁGENES + TEXTO)
# ==========================================
if st.session_state.img_portada and st.session_state.img_ficha:
    st.markdown("---")
    st.subheader("🎉 Imágenes Listas para Descargar")

    c_p1, c_p2 = st.columns(2)

    with c_p1:
        st.markdown("#### 🖼️ Foto 1: Portada (4 Fotos)")
        st.image(st.session_state.img_portada, use_container_width=True)
        st.download_button(
            label=f"📥 Descargar {st.session_state.nombre_portada}",
            data=st.session_state.img_portada,
            file_name=st.session_state.nombre_portada,
            mime="image/jpeg",
            type="primary",
            use_container_width=True
        )

    with c_p2:
        st.markdown("#### 📄 Foto 2: Ficha Técnica Gráfica")
        st.image(st.session_state.img_ficha, use_container_width=True)
        st.download_button(
            label=f"📥 Descargar {st.session_state.nombre_ficha}",
            data=st.session_state.img_ficha,
            file_name=st.session_state.nombre_ficha,
            mime="image/jpeg",
            type="primary",
            use_container_width=True
        )

    st.markdown("---")
    st.markdown("#### 📋 Ficha Publicitaria para WhatsApp / Redes")
    st.caption("Haz clic en el icono de **Copiar** en la esquina superior derecha del recuadro:")
    st.code(st.session_state.copy_publicitario, language="markdown")
