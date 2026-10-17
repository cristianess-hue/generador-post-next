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

def procesar_con_ia(url, og_title, og_desc, body_text):
    client = genai.Client(api_key=API_KEY)
    prompt = f"""
    Eres un analista inmobiliario profesional. Extrae los datos exactos del inmueble:
    URL: {url}
    Título: {og_title}
    Descripción: {og_desc}
    Texto: {body_text[:6000]}

    Instrucciones estrictas:
    1. 'colonia': Nombre del fraccionamiento o colonia (ej: "PRAGA RESIDENCIAL", "JARDÍN REAL", "MONTECARLO").
    2. 'tipo_inmueble': "Casa", "Departamento", "Local Comercial", "Oficina" o "Terreno".
    3. 'operacion': "Renta" o "Venta".
    4. 'precio': El precio con formato (ejemplo: "$10,000", "$3,580,000").
    5. 'moneda': "MXN" o "USD".
    6. 'recamaras': Número (ej: "2" o "3"). Si no se menciona, pon "".
    7. 'estacionamiento': Número de autos (ej: "1" o "2"). Si no se menciona, pon "".
    8. 'banos': Número (ej: "1", "2" o "2.5"). Si no se menciona, pon "".
    9. 'pisos': Número de plantas (ej: "1" o "2"). Si no se menciona, pon "1".
    10. 'terreno': Únicamente los m² de terreno si están EXPLÍCITAMENTE en el texto (ej: "128"). Si es renta, departamento o no existe terreno, DEBE SER VACÍO "".
    11. 'nombre_archivo': EXACTAMENTE con este formato: "[tipo_inmueble] en [colonia] [precio]" (ej: "Departamento en Praga Residencial $10,000" o "Casa en Montecarlo Residencial $3,580,000"). Sin caracteres especiales como / \\ : * ? " < > |.

    Devuelve un JSON estrictamente válido:
    {{
      "colonia": "PRAGA RESIDENCIAL",
      "tipo_inmueble": "Departamento",
      "operacion": "Renta",
      "precio": "$10,000",
      "moneda": "MXN",
      "recamaras": "2",
      "estacionamiento": "1",
      "banos": "1",
      "pisos": "1",
      "terreno": "",
      "nombre_archivo": "Departamento en Praga Residencial $10,000"
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

def pegar_icono(lienzo, clave_icono, x_centro, y_centro, max_size=52):
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
# GENERADOR GRÁFICO (1200x1200 px HD)
# ==========================================

def generar_flyer_cuadrado(datos, urls_4_fotos, asesor_nombre, asesor_datos):
    ancho, alto = 1200, 1200
    lienzo = PILImage.new("RGB", (ancho, alto), (255, 255, 255))
    draw = ImageDraw.Draw(lienzo)

    # Tipografías proporcionadas y legibles
    font_colonia = cargar_fuente(50, bold=True)
    font_tipo = cargar_fuente(34, bold=True)
    font_operacion = cargar_fuente(42, bold=True)
    font_precio = cargar_fuente(52, bold=True)
    font_moneda = cargar_fuente(22, bold=True)
    
    font_datos_num = cargar_fuente(38, bold=True)
    font_datos_lbl = cargar_fuente(18, bold=True)
    
    # Bloque inferior del asesor (grande y comercial)
    font_pie_nombre = cargar_fuente(42, bold=True)
    font_pie_tel = cargar_fuente(40, bold=True)
    font_pie_cargo = cargar_fuente(22, bold=False)
    font_pie_lema = cargar_fuente(20, bold=False)

    ROJO_NEXT = (227, 6, 19)
    GRIS_OSCURO = (30, 41, 59)
    GRIS_LINEA = (226, 232, 240)

    # 1. TÍTULO CENTRADO SOBRE LAS FOTOS (X: 330 a 1170 -> Centro exacto: 750)
    cx_fotos = 750
    colonia = datos.get("colonia", "PROPIEDAD").upper().strip()
    draw.text((cx_fotos, 60), colonia, fill=ROJO_NEXT, font=font_colonia, anchor="mm")

    # 2. COLUMNA IZQUIERDA (TIPO, OPERACIÓN Y PRECIO)
    cx_izq = 165
    draw.text((cx_izq, 85), datos.get("tipo_inmueble", "CASA").upper(), fill=GRIS_OSCURO, font=font_tipo, anchor="mm")
    draw.text((cx_izq, 135), datos.get("operacion", "Renta"), fill=ROJO_NEXT, font=font_operacion, anchor="mm")
    draw.text((cx_izq, 195), datos.get("precio", "$0"), fill=GRIS_OSCURO, font=font_precio, anchor="mm")
    draw.text((cx_izq, 235), datos.get("moneda", "MXN"), fill=GRIS_OSCURO, font=font_moneda, anchor="mm")

    y_linea = 265
    draw.line([(30, y_linea), (300, y_linea)], fill=GRIS_LINEA, width=2)

    # 3. ESPECIFICACIONES CON ICONOS
    # Fila 1: Recámaras y Estacionamiento
    y_r1 = y_linea + 55
    rec_val = str(datos.get("recamaras", "-")) or "-"
    draw.text((cx_izq - 65, y_r1), rec_val, fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq - 65, y_r1 + 28), "RECAMARAS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "recamaras", cx_izq - 65, y_r1 + 70, max_size=52)

    est_val = str(datos.get("estacionamiento", "-")) or "-"
    draw.text((cx_izq + 65, y_r1), est_val, fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq + 65, y_r1 + 28), "ESTAC.", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "estac", cx_izq + 65, y_r1 + 70, max_size=52)

    y_sep1 = y_r1 + 115
    draw.line([(30, y_sep1), (300, y_sep1)], fill=GRIS_LINEA, width=2)

    # Fila 2: Baños y Pisos
    y_r2 = y_sep1 + 55
    ban_val = str(datos.get("banos", "-")) or "-"
    draw.text((cx_izq - 65, y_r2), ban_val, fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq - 65, y_r2 + 28), "BAÑOS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "banos", cx_izq - 65, y_r2 + 70, max_size=52)

    pis_val = str(datos.get("pisos", "1")) or "1"
    draw.text((cx_izq + 65, y_r2), pis_val, fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq + 65, y_r2 + 28), "PISOS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "pisos", cx_izq + 65, y_r2 + 70, max_size=52)

    y_sep2 = y_r2 + 115
    draw.line([(30, y_sep2), (300, y_sep2)], fill=GRIS_LINEA, width=2)

    # Fila 3: Terreno (SOLO SI TIENE INFORMACIÓN)
    terreno_val = str(datos.get("terreno", "")).strip()
    if terreno_val and terreno_val not in ["0", "-", ""]:
        y_r3 = y_sep2 + 55
        draw.text((cx_izq, y_r3), terreno_val, fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
        draw.text((cx_izq, y_r3 + 28), "TERRENO m2", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
        pegar_icono(lienzo, "terreno", cx_izq, y_r3 + 70, max_size=52)
        draw.line([(30, y_r3 + 115), (300, y_r3 + 115)], fill=GRIS_LINEA, width=2)

    # 4. 4 FOTOS EN ALTA RESOLUCIÓN
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

    # 5. TARJETA INFERIOR DEL ASESOR (AMPLIADA)
    foto_ruta = asesor_datos.get("foto", "")
    if foto_ruta and os.path.exists(foto_ruta):
        try:
            foto_asesor = PILImage.open(foto_ruta).convert("RGBA")
            # Dimensiones mayores para llenar el espacio
            foto_asesor.thumbnail((210, 240), PILImage.Resampling.LANCZOS)
            draw.rounded_rectangle([(30, 910), (245, 1165)], radius=16, outline=(254, 205, 211), width=4)
            px = int(30 + (215 - foto_asesor.width) / 2)
            py = int(910 + (255 - foto_asesor.height) / 2)
            lienzo.paste(foto_asesor, (px, py), mask=foto_asesor if "A" in foto_asesor.getbands() else None)
        except Exception:
            pass

    # 6. CONTACTO CENTRAL INFERIOR
    cx_contacto = 560
    draw.text((cx_contacto, 975), asesor_nombre.upper(), fill=ROJO_NEXT, font=font_pie_nombre, anchor="mm")
    draw.text((cx_contacto, 1025), asesor_datos.get("telefono", ""), fill=(51, 65, 85), font=font_pie_tel, anchor="mm")
    draw.text((cx_contacto, 1070), "ASESOR INMOBILIARIO ASOCIADO", fill=(100, 116, 139), font=font_pie_cargo, anchor="mm")
    draw.text((cx_contacto, 1110), f'"{asesor_datos.get("lema", "")}"', fill=(148, 163, 184), font=font_pie_lema, anchor="mm")

    # 7. LOGO NEXT EN ESQUINA INFERIOR DERECHA (AMPLIADO)
    if os.path.exists(LOGO_PATH):
        try:
            logo = PILImage.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((320, 150), PILImage.Resampling.LANCZOS)
            lienzo.paste(logo, (840, 980), mask=logo if "A" in logo.getbands() else None)
        except Exception:
            pass

    buf = io.BytesIO()
    lienzo.save(buf, format="JPEG", quality=100, subsampling=0)
    buf.seek(0)
    return buf.getvalue()

# ==========================================
# INTERFAZ STREAMLIT
# ==========================================

st.title("🖼️ Generador de Post Cuadrado para Redes (1200x1200)")
st.write("Pega el enlace de la propiedad para extraer los datos automáticamente y seleccionar las fotos:")

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
        with st.spinner("Analizando portal y extrayendo fotos..."):
            try:
                og_t, og_d, b_txt, fotos = extraer_datos_inmueble(url_input.strip())
                datos = procesar_con_ia(url_input.strip(), og_t, og_d, b_txt)
                st.session_state.datos_extraidos = datos
                st.session_state.fotos_extraidas = fotos
                st.success(f"¡Propiedad analizada con éxito! ({datos.get('tipo_inmueble', '')} en {datos.get('colonia', '')} - {datos.get('precio', '')})")
            except Exception as e:
                st.error(f"Error al analizar el portal: {e}")

# ==========================================
# ASIGNACIÓN DE FOTOS Y DESCARGA
# ==========================================
if st.session_state.datos_extraidos and st.session_state.fotos_extraidas:
    st.markdown("---")
    st.subheader("📸 Selecciona las 4 fotos para el post:")

    fotos = st.session_state.fotos_extraidas
    cols_preview = st.columns(min(6, len(fotos)))
    for idx, f_url in enumerate(fotos):
        with cols_preview[idx % 6]:
            st.image(f_url, caption=f"Foto #{idx + 1}", use_container_width=True)

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
            st.image(img_resultado, caption="Vista Previa en Alta Definición", use_container_width=True)

            nombre_base = datos.get("nombre_archivo", f"{datos.get('tipo_inmueble', 'Inmueble')} en {datos.get('colonia', 'Propiedad')} {datos.get('precio', '')}")
            nombre_limpio = re.sub(r'[\\/*?:"<>|]', "", nombre_base).strip()
            nombre_archivo = f"{nombre_limpio}.jpg"

            st.download_button(
                label=f"📥 Descargar {nombre_archivo}",
                data=img_resultado,
                file_name=nombre_archivo,
                mime="image/jpeg",
                type="primary",
                use_container_width=True
            )
