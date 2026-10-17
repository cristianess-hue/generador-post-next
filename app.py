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

# Configuración de asesores con lemas, teléfonos y fotos individuales
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

# Iconos locales
ICONOS = {
    "recamaras": "ico_cama.png",
    "estac": "ico_auto.png",
    "banos": "ico_bano.png",
    "pisos": "ico_pisos.png",
    "terreno": "ico_terreno.png"
}

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
    Eres un analista inmobiliario. Extrae los datos exactos para un flyer publicitario:
    URL: {url}
    Título: {og_title}
    Descripción: {og_desc}
    Texto: {body_text[:6000]}

    Instrucciones estrictas:
    1. 'colonia': Nombre del fraccionamiento o colonia (ej: "JARDÍN REAL", "MONTECARLO").
    2. 'subtitulo': "RESIDENCIAL", "NORTE", "PONIENTE" o vacío según aplique.
    3. 'tipo_inmueble': "CASAS", "DEPARTAMENTO", "LOCAL COMERCIAL" o "TERRENO".
    4. 'operacion': "Renta" o "Venta".
    5. 'precio': Solo el monto con formato (ej: "$14,000" o "$3,580,000").
    6. 'moneda': "MXN" o "USD".
    7. 'recamaras': Número (ej: "3").
    8. 'estacionamiento': Número de autos (ej: "2").
    9. 'banos': Número (ej: "3" o "2.5").
    10. 'pisos': Número de plantas o niveles (ej: "2" o "1").
    11. 'terreno': Metros cuadrados de terreno si existen (ej: "128" o "148").

    Devuelve un JSON estrictamente válido:
    {{
      "colonia": "JARDÍN REAL",
      "subtitulo": "RESIDENCIAL",
      "tipo_inmueble": "CASAS",
      "operacion": "Renta",
      "precio": "$14,000",
      "moneda": "MXN",
      "recamaras": "3",
      "estacionamiento": "2",
      "banos": "3",
      "pisos": "2",
      "terreno": "128"
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
    r = requests.get(url, headers=headers, timeout=10)
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

def pegar_icono(lienzo, clave_icono, x_centro, y_centro, max_size=32):
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
# GENERADOR GRÁFICO (PIL 1080x1080)
# ==========================================

def generar_flyer_cuadrado(datos, urls_4_fotos, asesor_nombre, asesor_datos):
    ancho, alto = 1080, 1080
    lienzo = PILImage.new("RGB", (ancho, alto), (255, 255, 255))
    draw = ImageDraw.Draw(lienzo)

    try:
        font_titulo = ImageFont.truetype("arialbd.ttf", 36)
        font_sub = ImageFont.truetype("arialbd.ttf", 30)
        font_precio = ImageFont.truetype("arialbd.ttf", 40)
        font_operacion = ImageFont.truetype("arialbd.ttf", 34)
        font_datos_num = ImageFont.truetype("arialbd.ttf", 26)
        font_datos_lbl = ImageFont.truetype("arialbd.ttf", 15)
        font_pie_bold = ImageFont.truetype("arialbd.ttf", 28)
        font_pie_tel = ImageFont.truetype("arialbd.ttf", 28)
        font_pie_sub = ImageFont.truetype("arial.ttf", 15)
        font_lema = ImageFont.truetype("ariali.ttf", 14)
    except Exception:
        font_titulo = ImageFont.load_default()
        font_sub = font_titulo
        font_precio = font_titulo
        font_operacion = font_titulo
        font_datos_num = font_datos_lbl = font_titulo
        font_pie_bold = font_pie_tel = font_pie_sub = font_lema = font_titulo

    ROJO_NEXT = (227, 6, 19)
    GRIS_OSCURO = (35, 35, 35)
    GRIS_LINEA = (220, 220, 220)

    # 1. TEXTOS COLUMNA IZQUIERDA
    cx_izq = 145

    colonia = datos.get("colonia", "RESIDENCIAL").upper()
    subt = datos.get("subtitulo", "").upper()
    draw.text((cx_izq, 70), colonia, fill=ROJO_NEXT, font=font_titulo, anchor="mm")
    if subt:
        draw.text((cx_izq, 108), subt, fill=ROJO_NEXT, font=font_sub, anchor="mm")

    draw.text((cx_izq, 155), datos.get("tipo_inmueble", "CASAS").upper(), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq, 205), datos.get("operacion", "Renta"), fill=ROJO_NEXT, font=font_operacion, anchor="mm")

    draw.text((cx_izq, 265), datos.get("precio", "$0"), fill=GRIS_OSCURO, font=font_precio, anchor="mm")
    draw.text((cx_izq, 302), datos.get("moneda", "MXN"), fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")

    draw.line([(30, 325), (260, 325)], fill=GRIS_LINEA, width=2)

    # 2. ESPECIFICACIONES CON ICONOS
    # Fila 1: Recámaras y Estacionamiento
    y_r1 = 375
    draw.text((cx_izq - 60, y_r1), str(datos.get("recamaras", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq - 60, y_r1 + 22), "RECAMARAS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "recamaras", cx_izq - 60, y_r1 + 52)

    draw.text((cx_izq + 60, y_r1), str(datos.get("estacionamiento", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq + 60, y_r1 + 22), "ESTAC.", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "estac", cx_izq + 60, y_r1 + 52)

    draw.line([(30, 455), (260, 455)], fill=GRIS_LINEA, width=2)

    # Fila 2: Baños y Pisos
    y_r2 = 495
    draw.text((cx_izq - 60, y_r2), str(datos.get("banos", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq - 60, y_r2 + 22), "BAÑOS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "banos", cx_izq - 60, y_r2 + 52)

    draw.text((cx_izq + 60, y_r2), str(datos.get("pisos", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq + 60, y_r2 + 22), "PISOS", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "pisos", cx_izq + 60, y_r2 + 52)

    draw.line([(30, 575), (260, 575)], fill=GRIS_LINEA, width=2)

    # Fila 3: Terreno
    y_r3 = 615
    draw.text((cx_izq, y_r3), str(datos.get("terreno", "-")), fill=GRIS_OSCURO, font=font_datos_num, anchor="mm")
    draw.text((cx_izq, y_r3 + 22), "TERRENO m2", fill=GRIS_OSCURO, font=font_datos_lbl, anchor="mm")
    pegar_icono(lienzo, "terreno", cx_izq, y_r3 + 52)

    draw.line([(30, 695), (260, 695)], fill=GRIS_LINEA, width=2)

    # 3. 4 FOTOS EN CUADRÍCULA DERECHA
    x_col1 = 295
    x_col2 = 685
    y_fila1 = 110
    y_fila2 = 460
    foto_w, foto_h = 365, 330

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

    # 4. FOTO INDIVIDUAL DEL ASESOR
    foto_ruta = asesor_datos.get("foto", "")
    if foto_ruta and os.path.exists(foto_ruta):
        try:
            foto_asesor = PILImage.open(foto_ruta).convert("RGBA")
            # Proporción para la tarjeta
            foto_asesor.thumbnail((160, 180), PILImage.Resampling.LANCZOS)
            draw.rounded_rectangle([(35, 750), (205, 950)], radius=12, outline=(255, 182, 193), width=4)
            lienzo.paste(foto_asesor, (40, 755), mask=foto_asesor if "A" in foto_asesor.getbands() else None)
        except Exception:
            pass

    # 5. CONTACTO CENTRAL INFERIOR
    cx_contacto = 510
    draw.text((cx_contacto, 825), asesor_nombre.upper(), fill=ROJO_NEXT, font=font_pie_bold, anchor="mm")
    draw.text((cx_contacto, 865), asesor_datos.get("telefono", ""), fill=(80, 80, 80), font=font_pie_tel, anchor="mm")
    draw.text((cx_contacto, 905), "ASESOR INMOBILIARIO ASOCIADO", fill=(120, 120, 120), font=font_pie_sub, anchor="mm")
    
    # Lema personalizado
    lema_texto = f'"{asesor_datos.get("lema", "")}"'
    draw.text((cx_contacto, 940), lema_texto, fill=(100, 116, 139), font=font_lema, anchor="mm")

    # 6. LOGO NEXT EN LA ESQUINA INFERIOR DERECHA
    if os.path.exists(LOGO_PATH):
        try:
            logo = PILImage.open(LOGO_PATH).convert("RGBA")
            logo.thumbnail((240, 100), PILImage.Resampling.LANCZOS)
            lienzo.paste(logo, (770, 835), mask=logo if "A" in logo.getbands() else None)
        except Exception:
            pass

    buf = io.BytesIO()
    lienzo.save(buf, format="JPEG", quality=95)
    buf.seek(0)
    return buf.getvalue()

# ==========================================
# INTERFAZ STREAMLIT
# ==========================================

st.title("🖼️ Generador de Post Cuadrado para Redes")
st.write("Pega el enlace de la propiedad para extraer los datos y seleccionar qué foto va en cada posición:")

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
st.caption(f"📲 Teléfono asignado: **{info_asesor['telefono']}** | Lema: *\"{info_asesor['lema']}\"*")

if st.button("🔍 Extraer Información y Catálogo de Fotos", type="primary"):
    if not url_input.strip().startswith("http"):
        st.error("Por favor ingresa un enlace válido.")
    elif not API_KEY:
        st.error("Falta configurar GEMINI_API_KEY en los Secrets.")
    else:
        with st.spinner("Analizando portal y extrayendo fotos..."):
            try:
                og_t, og_d, b_txt, fotos = extraer_datos_inmueble(url_input.strip())
                datos = procesar_con_ia(url_input.strip(), og_t, og_d, b_txt)
                st.session_state.datos_extraidos = datos
                st.session_state.fotos_extraidas = fotos
                st.success(f"¡Propiedad analizada! Se encontraron {len(fotos)} imágenes.")
            except Exception as e:
                st.error(f"Error en la extracción: {e}")

# ==========================================
# PASO 2: ASIGNACIÓN VISUAL DE FOTOS
# ==========================================
if st.session_state.datos_extraidos and st.session_state.fotos_extraidas:
    st.markdown("---")
    st.subheader("📸 Selecciona las 4 fotos para el Post")
    
    fotos = st.session_state.fotos_extraidas
    cols_preview = st.columns(min(6, len(fotos)))
    for idx, f_url in enumerate(fotos):
        with cols_preview[idx % 6]:
            st.image(f_url, caption=f"Foto #{idx + 1}", use_container_width=True)

    opciones = list(range(1, len(fotos) + 1))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        f1_idx = st.selectbox("1. Principal (Arriba Izq):", opciones, index=0)
    with c2:
        f2_idx = st.selectbox("2. Detalle (Arriba Der):", opciones, index=min(1, len(fotos)-1))
    with c3:
        f3_idx = st.selectbox("3. Interior (Abajo Izq):", opciones, index=min(2, len(fotos)-1))
    with c4:
        f4_idx = st.selectbox("4. Espacio (Abajo Der):", opciones, index=min(3, len(fotos)-1))

    st.markdown("---")
    st.subheader("✏️ Verificar Datos del Inmueble")
    datos = st.session_state.datos_extraidos
    
    cd1, cd2, cd3, cd4 = st.columns(4)
    with cd1:
        datos["colonia"] = st.text_input("Colonia/Fracc:", value=datos.get("colonia", ""))
        datos["subtitulo"] = st.text_input("Subtítulo (ej: RESIDENCIAL):", value=datos.get("subtitulo", ""))
    with cd2:
        datos["tipo_inmueble"] = st.text_input("Tipo:", value=datos.get("tipo_inmueble", "CASAS"))
        datos["operacion"] = st.selectbox("Operación:", ["Renta", "Venta"], index=0 if datos.get("operacion") == "Renta" else 1)
    with cd3:
        datos["precio"] = st.text_input("Precio:", value=datos.get("precio", "$0"))
        datos["moneda"] = st.text_input("Moneda:", value=datos.get("moneda", "MXN"))
    with cd4:
        datos["recamaras"] = st.text_input("Recámaras:", value=datos.get("recamaras", "3"))
        datos["estacionamiento"] = st.text_input("Estac.:", value=datos.get("estacionamiento", "2"))
        datos["banos"] = st.text_input("Baños:", value=datos.get("banos", "2"))
        datos["pisos"] = st.text_input("Pisos:", value=datos.get("pisos", "2"))
        datos["terreno"] = st.text_input("Terreno m2:", value=datos.get("terreno", "128"))

    if st.button("✨ Generar Flyer Cuadrado JPG", type="primary", use_container_width=True):
        urls_seleccionadas = [
            fotos[f1_idx - 1],
            fotos[f2_idx - 1],
            fotos[f3_idx - 1],
            fotos[f4_idx - 1]
        ]
        with st.spinner("Ensamblando imagen en alta resolución..."):
            img_resultado = generar_flyer_cuadrado(datos, urls_seleccionadas, asesor_seleccionado, info_asesor)
            st.image(img_resultado, caption="Resultado Final", use_container_width=True)
            
            nombre_archivo = f"Post_{datos['colonia'].replace(' ', '_')}_{asesor_seleccionado.split()[0]}.jpg"
            st.download_button(
                label="📥 Descargar Imagen JPG (1080x1080)",
                data=img_resultado,
                file_name=nombre_archivo,
                mime="image/jpeg",
                type="primary",
                use_container_width=True
            )
