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
    "recamaras": "ico_cama.png",
    "estac": "ico_auto.png",
    "banos": "ico_bano.png",
    "pisos": "ico_pisos.png",
    "terreno": "ico_terreno.png"
}

# ==========================================
# GESTIÓN DE FUENTES NÍTIDAS (DESCARGA AUTOMÁTICA)
# ==========================================

@st.cache_resource
def obtener_fuente_bold(size):
    ruta_font = "Roboto-Bold.ttf"
    if not os.path.exists(ruta_font):
        url = "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Bold.ttf"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                with open(ruta_font, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass
    try:
        return ImageFont.truetype(ruta_font, size)
    except Exception:
        return ImageFont.load_default()

@st.cache_resource
def obtener_fuente_regular(size):
    ruta_font = "Roboto-Regular.ttf"
    if not os.path.exists(ruta_font):
        url = "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                with open(ruta_font, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass
    try:
        return ImageFont.truetype(ruta_font, size)
    except Exception:
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

def procesar_con_ia(url, og_title, og_desc, body_text):
    client = genai.Client(api_key=API_KEY)
    prompt = f"""
    Eres un analista inmobiliario profesional. Extrae los datos exactos del inmueble:
    URL: {url}
    Título: {og_title}
    Descripción: {og_desc}
    Texto: {body_text[:6000]}

    Instrucciones estrictas:
    1. 'linea1': Nombre del fraccionamiento/colonia (ejemplo: "JARDÍN REAL", "PRAGA").
    2. 'linea2': Subtítulo o tipo de desarrollo ("RESIDENCIAL", "NORTE", "CAMPESINO"). SI 'linea1' ya incluye la palabra (ej: 'PRAGA RESIDENCIAL'), déjalo VACÍO "". NUNCA repitas palabras entre linea1 y linea2.
    3. 'tipo_inmueble': "CASAS", "DEPARTAMENTO", "LOCAL" o "TERRENO".
    4. 'operacion': "Renta" o "Venta".
    5. 'precio': El precio con formato (ejemplo: "$10,000", "$3,580,000").
    6. 'moneda': "MXN" o "USD".
    7. 'recamaras': Número (ej: "2"). Si no dice nada, déjalo vacío "".
    8. 'estacionamiento': Número de autos (ej: "1" o "2"). Si no dice nada, déjalo vacío "".
    9. 'banos': Número (ej: "1" o "2.5"). Si no dice nada, déjalo vacío "".
    10. 'pisos': Número de plantas o niveles (ej: "1" o "2"). Si no dice nada, pon "1".
    11. 'terreno': Solo los m² de terreno si están EXPLÍCITAMENTE en el texto (ej: "128"). Si es renta, departamento o no menciona terreno, DEBE SER OBLIGATORIAMENTE cadena vacía "".

    Devuelve un JSON estrictamente válido:
    {{
      "linea1": "PRAGA",
      "linea2": "RESIDENCIAL",
      "tipo_inmueble": "DEPARTAMENTO",
      "operacion": "Renta",
      "precio": "$10,000",
      "moneda": "MXN",
      "recamaras": "2",
      "estacionamiento": "1",
      "banos": "1",
      "pisos": "1",
      "terreno": ""
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
            return json.loads(res.text)
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

def pegar_icono(lienzo, clave_icono, x_centro, y_centro, max_size=42):
    ruta = ICONOS.get(clave_icono)
    if ruta and os.path.exists(ruta):
        try:
            ico = PILImage.open(ruta).convert("RGBA")
            ico.thumbnail((max_size, max_size), PILImage.Resampling.LANCZOS)
            px = int(x_centro - (ico.width / 2))
            py = int(y_centro - (ico.height / 2))
            lienzo.paste(ico, (px, py), mask=ico)
        except Exception:
            pass

# ==========================================
# GENERADOR GRÁFICO ULTRA HD (1200x1200 px)
# ==========================================

def generar_flyer_cuadrado(datos, urls_4_fotos, asesor_nombre, asesor_datos):
    ancho, alto = 1200, 1200
    lienzo = PILImage.new("RGB", (ancho, alto), (255, 255, 255))
    draw = ImageDraw.Draw(lienzo)

    # Fuentes vectoriales de alta definición
    font_titulo = obtener_fuente_bold(44)
    font_sub = obtener_fuente_bold(36)
    font_tipo = obtener_fuente_bold(30)
    font_operacion = obtener_fuente_bold(38)
    font_precio = obtener_fuente_bold(46)
    font_moneda = obtener_fuente_bold(18)
    
    font_datos_num = obtener_fuente_bold(32)
    font_datos_lbl = obtener_fuente_bold(18)
    
    font_pie_bold = obtener_fuente_bold(30)
    font_pie_tel = obtener_fuente_bold(30)
    font_pie_sub = obtener_fuente_regular(17)
    font_lema = obtener_fuente_regular(16)

    ROJO_NEXT = (227, 6, 19)
    GRIS_OSCURO = (30, 41, 59)
    GRIS_LINEA = (226, 232, 240)

    # 1. ENCABEZADO Y PRECIO (COLUMNA IZQUIERDA)
    cx_izq = 165

    linea1 = datos.get("linea1", "PROPIEDAD").upper().strip()
    linea2 = datos.get("linea2", "").upper().strip()

    draw.text((cx_izq, 75), linea1, fill=ROJO_NEXT, font=font_titulo, anchor="mm")
    y_sig = 120
    if linea2 and linea2 != linea1:
        draw.text((cx_izq, y_sig), linea2, fill=ROJO_NEXT, font=font_sub, anchor="mm")
        y_sig += 45

    draw.text((cx_izq, y_sig + 15), datos.get("tipo_inmueble", "CASA").upper(), fill=GRIS_OSCURO, font=font_tipo, anchor="mm")
    draw.text((cx_izq, y_sig + 70), datos.get("operacion", "Renta"), fill=ROJO_NEXT, font=font_operacion, anchor="mm")
    draw.text((cx_izq, y_sig + 135), datos.get("precio", "$0"), fill=GRIS_OSCURO, font=font_precio, anchor="mm")
    draw.text((cx_izq, y_sig + 175), datos.get("moneda", "MXN"), fill=GRIS_OSCURO, font=font_moneda, anchor="mm")

    draw.line([(30, y_sig + 205), (300, y_sig + 205)], fill=GRIS_LINEA, width=2)

    # 2. ESPECIFICACIONES CON ICONOS
    # Fila 1: Recámaras y Estacionamiento
    y_r1 = y_sig + 265
    draw.text((cx_izq - 65, y_r1), str(datos.get("recamaras", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq - 65, y_r1 + 25), "RECAMARAS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "recamaras", cx_izq - 65, y_r1 + 65, max_size=42)

    draw.text((cx_izq + 65, y_r1), str(datos.get("estacionamiento", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq + 65, y_r1 + 25), "ESTAC.", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "estac", cx_izq + 65, y_r1 + 65, max_size=42)

    draw.line([(30, y_r1 + 105), (300, y_r1 + 105)], fill=GRIS_LINEA, width=2)

    # Fila 2: Baños y Pisos
    y_r2 = y_r1 + 155
    draw.text((cx_izq - 65, y_r2), str(datos.get("banos", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq - 65, y_r2 + 25), "BAÑOS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "banos", cx_izq - 65, y_r2 + 65, max_size=42)

    draw.text((cx_izq + 65, y_r2), str(datos.get("pisos", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq + 65, y_r2 + 25), "PISOS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "pisos", cx_izq + 65, y_r2 + 65, max_size=42)

    # Fila 3: Terreno (SOLO SI TIENE INFORMACIÓN)
    terreno_val = str(datos.get("terreno", "")).strip()
    if terreno_val and terreno_val not in ["0", "-", ""]:
        draw.line([(30, y_r2 + 105), (300, y_r2 + 105)], fill=GRIS_LINEA, width=2)
        y_r3 = y_r2 + 155
        draw.text((cx_izq, y_r3), terreno_val, fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
        draw.text((cx_izq, y_r3 + 25), "TERRENO m2", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
        pegar_icono(lienzo, "terreno", cx_izq, y_r3 + 65, max_size=42)
        draw.line([(30, y_r3 + 105), (300, y_r3 + 105)], fill=GRIS_LINEA, width=2)
    else:
        draw.line([(30, y_r2 + 105), (300, y_r2 + 105)], fill=GRIS_LINEA, width=2)

    # 3. 4 FOTOGRAFÍAS EN ALTA DEFINICIÓN (CUADRÍCULA NÍTIDA)
    x_col1 = 330
    x_col2 = 765
    y_fila1 = 110
    y_fila2 = 505
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

    # 4. TARJETA INFERIOR DEL ASESOR
    foto_ruta = asesor_datos.get("foto", "")
    if foto_ruta and os.path.exists(foto_ruta):
        try:
            foto_asesor = PILImage.open(foto_ruta).convert("RGBA")
            foto_asesor.thumbnail((180, 200), PILImage.Resampling.LANCZOS)
            draw.rounded_rectangle([(35, 930), (225, 1150)], radius=14, outline=(254, 205, 211), width=4)
            px = int(35 + (190 - foto_asesor.width) / 2)
            py = int(930 + (220 - foto_asesor.height) / 2)
            lienzo.paste(foto_asesor, (px, py), mask=foto_asesor if "A" in foto_asesor.getbands() else None)
        except Exception:
            pass

    # 5. CONTACTO CENTRAL INFERIOR
    cx_contacto = 570
    draw.text((cx_contacto, 990), asesor_nombre.upper(), fill=ROJO_NEXT, font=font_pie_bold, anchor="mm")
    draw.text((cx_contacto, 1035), asesor_datos.get("telefono", ""), fill=(51, 65, 85), font=font_pie_tel, anchor="mm")
    draw.text((cx_contacto, 1075), "ASESOR INMOBILIARIO ASOCIADO", fill=(100, 116, 139), font=font_pie_sub, anchor="mm")
    draw.text((cx_contacto, 1115), f'"{asesor_datos.get("lema", "")}"', fill=(148, 163, 184), font=font_lema, anchor="mm")

    # 6. LOGO NEXT INFERIOR DERECHO
    if os.path.exists(LOGO_PATH):
        try:
            logo = PILImage.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((260, 120), PILImage.Resampling.LANCZOS)
            lienzo.paste(logo, (880, 1000), mask=logo if "A" in logo.getbands() else None)
        except Exception:
            pass

    buf = io.BytesIO()
    lienzo.save(buf, format="JPEG", quality=100, subsampling=0)
    buf.seek(0)
    return buf.getvalue()

# ==========================================
# INTERFAZ STREAMLIT LIMPIA (SIN CAMPOS MANUALES)
# ==========================================

st.title("🖼️ Generador de Post Cuadrado para Redes (1200x1200)")
st.write("Ingresa el enlace de la propiedad para extraer los datos automáticamente y seleccionar las 4 fotos:")

if "datos_extraidos" not in st.session_state:
    st.session_state.datos_extraidos = None
if "fotos_extraidas" not in st.session_state:
    st.session_state.fotos_extraidas = []

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
        with st.spinner("Analizando inmueble y extrayendo catálogo..."):
            try:
                og_t, og_d, b_txt, fotos = extraer_datos_inmueble(url_input.strip())
                datos = procesar_con_ia(url_input.strip(), og_t, og_d, b_txt)
                st.session_state.datos_extraidos = datos
                st.session_state.fotos_extraidas = fotos
                st.success(f"¡Propiedad extraída con éxito! ({datos.get('linea1', '')} - {datos.get('precio', '')})")
            except Exception as e:
                st.error(f"Error al analizar el portal: {e}")

# ==========================================
# ASIGNACIÓN DE FOTOS Y GENERACIÓN DIRECTA
# ==========================================
if st.session_state.datos_extraidos and st.session_state.fotos_extraidas:
    st.markdown("---")
    st.subheader("📸 Selecciona las 4 fotos que compondrán el post:")

    fotos = st.session_state.fotos_extraidas
    cols_preview = st.columns(min(6, len(fotos)))
    for idx, f_url in enumerate(fotos):
        with cols_preview[idx % 6]:
            st.image(f_url, caption=f"Foto #{idx + 1}", use_container_width=True)

    opciones = list(range(1, len(fotos) + 1))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        f1_idx = st.selectbox("1. Fachada / Principal (Arr. Izq):", opciones, index=0)
    with c2:
        f2_idx = st.selectbox("2. Sala / Cocina (Arr. Der):", opciones, index=min(1, len(fotos)-1))
    with c3:
        f3_idx = st.selectbox("3. Comedor / Recámara (Abj. Izq):", opciones, index=min(2, len(fotos)-1))
    with c4:
        f4_idx = st.selectbox("4. Detalle / Baño (Abj. Der):", opciones, index=min(3, len(fotos)-1))

    st.markdown("---")
    
    if st.button("✨ Generar Flyer Cuadrado JPG (Ultra HD)", type="primary", use_container_width=True):
        urls_seleccionadas = [
            fotos[f1_idx - 1],
            fotos[f2_idx - 1],
            fotos[f3_idx - 1],
            fotos[f4_idx - 1]
        ]
        with st.spinner("Componiendo imagen nítida en alta resolución..."):
            datos = st.session_state.datos_extraidos
            img_resultado = generar_flyer_cuadrado(datos, urls_seleccionadas, asesor_seleccionado, info_asesor)
            st.image(img_resultado, caption="Vista Previa de Alta Resolución", use_container_width=True)

            nombre_archivo = f"Post_{datos.get('linea1', 'Propiedad').replace(' ', '_')}_{asesor_seleccionado.split()[0]}.jpg"
            st.download_button(
                label="📥 Descargar Flyer JPG (1200x1200)",
                data=img_resultado,
                file_name=nombre_archivo,
                mime="image/jpeg",
                type="primary",
                use_container_width=True
            )
