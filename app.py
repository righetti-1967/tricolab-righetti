# ============================================================================
# STUDIO TRICOLOGICO RIGHETTI SINCE 1967 - VERSIONE DEFINITIVA IBRIDA
# ============================================================================

import os
import sqlite3
import re
import base64
import textwrap
from datetime import datetime
import numpy as np
import pandas as pd
import cv2
import requests
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import fitz  # PyMuPDF
import warnings

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="🔬 Studio Tricologico Righetti Since 1967",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================================
# DATABASE (MULTI-UTENTE WAL + TIMEOUT)
# ============================================================================
def init_db():
    conn = sqlite3.connect("trico_database.db", timeout=30)
    c = conn.cursor()
    try:
        c.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass

    c.execute(
        """CREATE TABLE IF NOT EXISTS clienti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codice_cliente TEXT UNIQUE NOT NULL,
        sesso TEXT DEFAULT 'Uomo',
        data_registrazione TEXT DEFAULT CURRENT_TIMESTAMP
    )"""
    )

    # Migrazioni sicure: aggiunge le colonne se mancano nel database esistente
    for col_c in ["sesso", "cellulare", "email"]:
        try:
            c.execute(f"ALTER TABLE clienti ADD COLUMN {col_c} TEXT")
        except sqlite3.OperationalError:
            pass

    c.execute(
        """CREATE TABLE IF NOT EXISTS analisi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        data TEXT NOT NULL,
        zona TEXT,
        ingrandimento TEXT,
        luce TEXT,
        foto_caricate INTEGER,
        steli_totale INTEGER,
        steli_anagen INTEGER,
        steli_vellus INTEGER,
        steli_nuovi INTEGER,
        calibro_medio REAL,
        densita_f REAL,
        anisotropia REAL,
        perc_vellus REAL,
        eritemi INTEGER,
        dermatite_seborroica INTEGER,
        forfora_secca INTEGER,
        osti_intasati INTEGER,
        prurito TEXT,
        routine_consigliata TEXT,
        FOREIGN KEY (cliente_id) REFERENCES clienti(id)
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS categorie (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL
    )"""
    )

    c.execute("SELECT COUNT(*) FROM categorie")
    if c.fetchone()[0] == 0:
        default_cat = [
            ("Topico Cosmetico",),
            ("Integratore",),
            ("Probiotico",),
            ("Detergente",),
            ("Spray",),
            ("Altro",),
        ]
        c.executemany("INSERT INTO categorie (nome) VALUES (?)", default_cat)

    c.execute(
        """CREATE TABLE IF NOT EXISTS prodotti (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE,
        categoria TEXT,
        modalita TEXT,
        frequenza TEXT,
        orario TEXT,
        trigger_condizione TEXT,
        note TEXT,
        dosi TEXT,
        tempi_posa TEXT,
        durata_utilizzo TEXT
    )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS prodotti_cliente (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        prodotto_id INTEGER,
        modalita TEXT,
        frequenza TEXT,
        orario TEXT,
        note_utilizzo TEXT,
        dosi TEXT,
        tempi_posa TEXT,
        durata_utilizzo TEXT,
        data_assegnazione TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (cliente_id) REFERENCES clienti(id),
        FOREIGN KEY (prodotto_id) REFERENCES prodotti(id)
    )"""
    )

    for col in ["modalita", "frequenza", "orario"]:
        try:
            c.execute(f"ALTER TABLE prodotti_cliente ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass

    c.execute("SELECT COUNT(*) FROM prodotti")
    if c.fetchone()[0] == 0:
        prodotti_default = [
            (
                "Lozione Dermocosmetica Lenitiva (Fitosteroli & Niacinamide)",
                "Topico Cosmetico",
                "Applicare 2ml su cute asciutta",
                "Tutti i giorni",
                "Sera",
                "prurito_eritema",
                "Equilibrio microambiente cutaneo",
                "2ml",
                "10 minuti",
                "3 mesi",
            ),
            (
                "Lozione Nutritiva Stelo (Serenoa & Zaffiro)",
                "Topico Cosmetico",
                "Applicare 2ml con massaggio",
                "Tutti i giorni",
                "Sera",
                "miniaturizzazione",
                "Prevenzione capello Vellus",
                "2ml",
                "5 minuti",
                "6 mesi",
            ),
            (
                "Integratore Cheratinico (Cistina, Metionina, Zinco)",
                "Integratore",
                "1 compressa al giorno",
                "Tutti i giorni",
                "Mattino",
                "calibro_basso",
                "Supporto sintesi cheratinica",
                "1 compressa",
                "Con acqua",
                "3 mesi",
            ),
            (
                "Probiotico Cutaneo",
                "Probiotico",
                "1 capsula al giorno",
                "Tutti i giorni",
                "Mattino",
                "prurito",
                "Riequilibrio microbioma",
                "1 capsula",
                "A stomaco vuoto",
                "2 mesi",
            ),
            (
                "Shampoo Purificante Sebo-Regolatore",
                "Detergente",
                "Applicare e massaggiare",
                "2-3 volte/settimana",
                "Lavaggio",
                "prurito_eritema",
                "Libera osti follicolari",
                "5ml",
                "2 minuti",
                "Uso continuativo",
            ),
        ]
        c.executemany(
            """INSERT INTO prodotti 
            (nome, categoria, modalita, frequenza, orario, trigger_condizione, note, dosi, tempi_posa, durata_utilizzo) 
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            prodotti_default,
        )

    conn.commit()
    return conn


# ============================================================================
# PARSER ESTRATTORE PER VECCHI REPORT PDF
# ============================================================================
def estrai_dati_da_pdf_report(pdf_bytes):
    dati_estratti = {
        "checkup_num": "Precedente",
        "data": "Data non rilevata",
        "note_precedenti": "",
        "calibro_medio": 0.0,
        "anisotropia": 0.0,
        "densita_f": 0,
        "eritemi": 0,
        "tappi_sebacei": 0,
        "steli_nuovi": 0,
        "prodotti": "",
    }
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        testo_completo = ""

        for page in doc:
            widgets = page.widgets()
            if widgets:
                for w in widgets:
                    if w.field_name == "Text2" and w.field_value:
                        dati_estratti["checkup_num"] = str(w.field_value)
                    elif (
                        w.field_name in ["Date_af_date", "Date1_af_date"]
                        and w.field_value
                    ):
                        dati_estratti["data"] = str(w.field_value)
                    elif w.field_name == "Text4" and w.field_value:
                        dati_estratti["note_precedenti"] = str(w.field_value)
            testo_completo += page.get_text() + "\n"

        calibro_match = re.search(r"(\d+[\.,]?\d*)\s*µm", testo_completo, re.IGNORECASE)
        if calibro_match:
            dati_estratti["calibro_medio"] = float(
                calibro_match.group(1).replace(",", ".")
            )

        aniso_match = re.search(
            r"anisotropia\s*(?:del)?\s*(\d+[\.,]?\d*)\s*%",
            testo_completo,
            re.IGNORECASE,
        )
        if aniso_match:
            dati_estratti["anisotropia"] = float(aniso_match.group(1).replace(",", "."))

        den_match = re.search(r"(\d+)\s*capelli/cm[2²]", testo_completo, re.IGNORECASE)
        if den_match:
            dati_estratti["densita_f"] = int(den_match.group(1))

        doc.close()
    except Exception as e:
        st.warning(f"Lettura parziale del PDF: {e}")
    return dati_estratti


def genera_referto_dermocosmetico(dati, lente, luce, zona, parametri_cliente):
    punti_cute = []
    punti_osti = []

    if luce == "Polarizzata":
        if dati["eritema_diffuso"] > 1:
            punti_cute.append("iperemia dermica sottocutanea (luce polarizzata)")
    else:
        if dati["eritema_diffuso"] > 1:
            punti_cute.append("eritema diffuso")
        elif dati["eritema_diffuso"] == 1:
            punti_cute.append("lieve iperemia periostiale")

    if dati["sebo_ceroso"] > 1:
        punti_cute.append("sebo ceroso aderente")
    if dati["desquamazione_secca"] > 2:
        punti_cute.append("desquamazione secca lamellare")

    if dati["tappi_sebacei"] > 0:
        punti_osti.append(f"{dati['tappi_sebacei']} tappi sebacei/ipercheratosi")
    if dati["follicoli_dormienti"] > 0:
        punti_osti.append(
            f"{dati['follicoli_dormienti']} follicoli silenti (empty ostia)"
        )

    # Chiarimento Anagen Terminali vs Germogli
    steli_str = f"Calibro medio {dati['calibro_medio']} µm"
    if dati["anisotropia"] > 20.0:
        steli_str += f" (anisotropia {dati['anisotropia']}%)"
    else:
        steli_str += f" (omogeneità {dati['anisotropia']}%)"

    if dati.get("steli_anagen", 0) > 0:
        steli_str += f", {dati['steli_anagen']} anagen terminali sani"
    if dati.get("steli_nuovi", 0) > 0:
        steli_str += f", {dati['steli_nuovi']} germogli ricrescita"
    if dati.get("steli_vellus", 0) > 0:
        steli_str += f", {dati['steli_vellus']} vellus"

    testo = f"Area {zona} ({lente}, {luce.lower()}): "
    testo += (
        ("Cute con " + ", ".join(punti_cute) + ". ")
        if punti_cute
        else "Cute in equilibrio idrolipidico. "
    )
    testo += (
        ("Osti: " + ", ".join(punti_osti) + ". ") if punti_osti else "Osti ricettivi. "
    )
    testo += f"Steli: {steli_str}."
    return testo


# ============================================================================
# SINTESI GLOBALE OFFLINE (STRUTTURATA IN 8-9 RIGHE)
# ============================================================================
def genera_sintesi_globale_operatore(
    dati_sessione, parametri_cliente, dati_confronto=None
):
    sesso = parametri_cliente.get("sesso", "Uomo")
    scala = parametri_cliente.get("scala_alopecia", "Nessun diradamento evidente")
    quadro = parametri_cliente.get("quadro_ipotesi", "Standard")
    cal_m = dati_sessione.get("calibro_medio", 0.0)
    ani_m = dati_sessione.get("anisotropia", 0.0)
    den_m = dati_sessione.get("densita_f", 0)
    tot_tappi = dati_sessione.get("tappi_sebacei", 0)
    tot_eritemi = dati_sessione.get("eritemi", 0)
    tot_nuovi = dati_sessione.get("steli_nuovi", 0)

    # 1. Cute (2 righe)
    anomalie_cute = []
    if tot_eritemi > 2:
        anomalie_cute.append("evidente iperemia dermica e reattività vascolare")
    if parametri_cliente.get("sebo_eccesso"):
        anomalie_cute.append("ipersecrezione sebacea con film lipidico spesso")
    cute_str = (
        ", ".join(anomalie_cute)
        if anomalie_cute
        else "microambiente cutaneo integro in equilibrio idrolipidico"
    )
    r1 = f"1. Inquadramento & Cute: Paziente {sesso.lower()} ({scala.split(':')[0]}). Lo scalpo presenta {cute_str} correlato al quadro {quadro.lower()}."

    # 2. Osti (2 righe)
    if tot_tappi > 1:
        osti_str = f"presenza di ipercheratosi ostiale con {tot_tappi} tappi sebacei occludenti che ostacolano la normale traspirazione"
    else:
        osti_str = "pervietà ostiale ottimale con assenza di ostruzioni cheratiniche o depositi sebacei periostiali"
    r2 = f"2. Osti & Ancoraggio: Riscontro di {osti_str}."

    # 3. Fusti & Densità (2 righe)
    if ani_m > 20.0:
        fusti_str = f"calibro medio di {cal_m} µm con marcata anisotropia ({ani_m}%), indice di miniaturizzazione progressiva"
    elif ani_m > 12.0:
        fusti_str = f"calibro medio di {cal_m} µm con moderata disomogeneità ({ani_m}%)"
    else:
        fusti_str = f"buon trofismo degli steli (calibro medio {cal_m} µm, anisotropia {ani_m}%)"

    if den_m > 0:
        fusti_str += f" e densità stimata di {den_m} cap/cm²"
    if tot_nuovi > 0:
        fusti_str += f", con {tot_nuovi} germogli anagen in ricrescita"
    r3 = f"3. Fusti & Densità: Rilevato {fusti_str}."

    # 4. Chiusura staccata con riga vuota
    r4 = '4. Protocollo Soluzione: Vedere PDF allegato "Rituale di Cura Domiciliare".'

    return f"{r1}\n{r2}\n{r3}\n\n{r4}"


# ============================================================================
# MOTORE VISIONE TRICOSCOPICA CON DENSITÀ AD ALTA SENSIBILITÀ (FOTOTRICOGRAMMA)
# ============================================================================
def analizza_immagine_tricoscopica_pro(
    img_rgb,
    lente="50x",
    luce="Bianca",
    zona="Vertice",
    parametri_cliente=None,
):
    if parametri_cliente is None:
        parametri_cliente = {"sesso": "Uomo"}

    h_img, w_img = img_rgb.shape[:2]
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)
    h_chan, s_chan, v_chan = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    annotata = img_rgb.copy()

    # -------------------------------------------------------------
    # 1. RILEVAMENTO ERITEMA & IPEREMIA (SOTTOSTANTE ALLA CUTE)
    # -------------------------------------------------------------
    r, g, b = cv2.split(img_rgb)
    redness = r.astype(np.int16) - ((g.astype(np.int16) + b.astype(np.int16)) // 2)
    redness_mask = np.uint8(
        np.clip(redness * (1.4 if luce == "Polarizzata" else 1.0), 0, 255)
    )
    _, thresh_red = cv2.threshold(redness_mask, 44, 255, cv2.THRESH_BINARY)
    cnts_red, _ = cv2.findContours(
        thresh_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    eritemi = 0
    for c_cnt in cnts_red:
        if cv2.contourArea(c_cnt) > (400 if lente == "50x" else 180):
            M = cv2.moments(c_cnt)
            if M["m00"] != 0:
                cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
                if 30 < cx < w_img - 30 and 30 < cy < h_img - 30:
                    eritemi += 1
                    cv2.circle(annotata, (cx, cy), 5, (230, 20, 20), -1)
                    cv2.circle(annotata, (cx, cy), 7, (255, 255, 255), 1)

    # -------------------------------------------------------------
    # 2. RILEVAMENTO TAPPI SEBACEI / YELLOW DOTS
    # -------------------------------------------------------------
    mask_yellow = (h_chan >= 14) & (h_chan <= 38) & (s_chan >= 50) & (v_chan >= 130)
    cnts_yellow, _ = cv2.findContours(
        np.uint8(mask_yellow * 255),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    tappi = 0
    for y_cnt in cnts_yellow:
        if cv2.contourArea(y_cnt) > (300 if lente == "50x" else 100):
            M = cv2.moments(y_cnt)
            if M["m00"] != 0:
                cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
                if 30 < cx < w_img - 30 and 30 < cy < h_img - 30:
                    tappi += 1
                    cv2.circle(annotata, (cx, cy), 6, (245, 210, 0), -1)
                    cv2.circle(annotata, (cx, cy), 8, (0, 0, 0), 1)

    # -------------------------------------------------------------
    # 3. SEGMENTAZIONE FUSTI & ANALISI COPERTURA CUTE (FOTOTRICOGRAMMA)
    # -------------------------------------------------------------
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    mediana_cute = float(np.median(gray))

    # Maschera buio: isola i veri capelli scuri dalla cute chiara
    soglia_taglio = int(mediana_cute - 22)
    _, mask_scura = cv2.threshold(
        gray, max(35, soglia_taglio), 255, cv2.THRESH_BINARY_INV
    )

    k_size = 19 if lente == "50x" else 27
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_size, k_size))
    blackhat = cv2.morphologyEx(blur, cv2.MORPH_BLACKHAT, kernel)
    _, thresh_bh = cv2.threshold(
        blackhat, 14 if lente == "200x" else 18, 255, cv2.THRESH_BINARY
    )

    maschera_fusti = cv2.bitwise_and(thresh_bh, mask_scura)
    maschera_fusti = cv2.morphologyEx(
        maschera_fusti, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)
    )

    # Calcolo della percentuale di copertura dei capelli rispetto alla cute
    pixel_totali = float(h_img * w_img)
    pixel_fusti = float(cv2.countNonZero(maschera_fusti))
    percentuale_copertura = (pixel_fusti / pixel_totali) * 100.0  # es. 8% - 35%

    dist_transform = cv2.distanceTransform(maschera_fusti, cv2.DIST_L2, 5)
    contours, _ = cv2.findContours(
        maschera_fusti, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )

    spessori = []
    osti_rilevati = []
    steli_anagen = 0
    steli_vellus = 0
    steli_nuovi = 0

    min_area_val = 220 if lente == "50x" else 400
    scala_um = 9.8 if lente == "50x" else 4.2

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > min_area_val:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = float(max(w, h)) / max(min(w, h), 1)

            if aspect_ratio > 1.4:
                mask_cnt = np.zeros(gray.shape, dtype=np.uint8)
                cv2.drawContours(mask_cnt, [cnt], -1, 255, -1)

                vals = dist_transform[mask_cnt == 255]
                if len(vals) == 0:
                    continue

                if lente == "200x":
                    diametro_px = float(np.percentile(vals, 90)) * 2.0
                    spessore_um = round(diametro_px * 6.5, 1)
                else:
                    diametro_px = float(np.percentile(vals, 85)) * 2.0
                    spessore_um = round(diametro_px * 9.5, 1)

                if spessore_um < 25.0:
                    spessore_um = 30.0 if lente == "200x" else 28.0
                elif spessore_um > 105.0:
                    spessore_um = 82.0

                if 22.0 <= spessore_um <= 105.0:
                    [vx, vy, x0, y0] = cv2.fitLine(cnt, cv2.DIST_L2, 0, 0.01, 0.01)
                    pts = cnt.reshape(-1, 2)
                    proj = (pts[:, 0] - x0) * vx + (pts[:, 1] - y0) * vy
                    root_pt = pts[np.argmax(proj)]
                    rx, ry = int(root_pt[0]), int(root_pt[1])

                    # Filtro anti-bordo
                    if 35 < rx < w_img - 35 and 35 < ry < h_img - 35:
                        troppo_vicino = False
                        raggio_cluster = 35 if lente == "200x" else 22
                        for ox, oy in osti_rilevati:
                            if (
                                np.sqrt((rx - ox) ** 2 + (ry - oy) ** 2)
                                < raggio_cluster
                            ):
                                troppo_vicino = True
                                break

                        if not troppo_vicino:
                            osti_rilevati.append((rx, ry))
                            spessori.append(spessore_um)

                            if spessore_um < 35.0:
                                steli_vellus += 1
                            else:
                                steli_anagen += 1
                                cv2.circle(annotata, (rx, ry), 5, (40, 200, 80), -1)
                                cv2.circle(annotata, (rx, ry), 7, (255, 255, 255), 1)
                    else:
                        spessori.append(spessore_um)

    # -------------------------------------------------------------
    # 4. RILEVAMENTO FOLLICOLI SILENTI (EMPTY OSTIA)
    # -------------------------------------------------------------
    inv_hair = cv2.bitwise_not(maschera_fusti)
    mask_dormienti = (
        (s_chan > 25)
        & (s_chan < 85)
        & (v_chan > 160)
        & (inv_hair == 255)
        & (thresh_red == 0)
    )
    cnts_dorm, _ = cv2.findContours(
        np.uint8(mask_dormienti * 255),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    follicoli_dormienti = 0
    for c_cnt in cnts_dorm:
        area = cv2.contourArea(c_cnt)
        if 60 < area < 350 if lente == "50x" else 150 < area < 550:
            M = cv2.moments(c_cnt)
            if M["m00"] != 0:
                cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
                if 35 < cx < w_img - 35 and 35 < cy < h_img - 35:
                    if not any(
                        np.sqrt((cx - ox) ** 2 + (cy - oy) ** 2) < 25
                        for ox, oy in osti_rilevati
                    ):
                        follicoli_dormienti += 1
                        cv2.circle(annotata, (cx, cy), 5, (0, 215, 255), -1)
                        cv2.circle(annotata, (cx, cy), 7, (0, 0, 0), 1)

    calibro_m = round(float(np.mean(spessori)), 1) if spessori else 0.0
    anisotropia = (
        round((float(np.std(spessori)) / calibro_m) * 100, 1) if calibro_m > 0 else 0.0
    )

    # -------------------------------------------------------------
    # 5. CALCOLO DENSITÀ REALE CORRELATA ALLA CUTE SCOPERTA
    # -------------------------------------------------------------
    if lente == "50x":
        fusti_contati = len(osti_rilevati)

        # Calcolo ponderato: combina i fusti rilevati con la superficie reale occupata
        # Copertura normale sana: ~22-30%. Copertura con diradamento/riga: ~8-15%
        fattore_scalpo = np.clip(percentuale_copertura / 20.0, 0.55, 1.25)
        densita_base = (fusti_contati / 0.22) * fattore_scalpo

        densita_val = int(round(densita_base))
        # Limiti biologici reali (da diradamento severo 65 a capigliatura foltissima 240)
        densita_val = max(65, min(240, densita_val))
        densita_testo = f"{densita_val} cap/cm²"
    else:
        densita_val = 0
        num_fusti = len(osti_rilevati)
        densita_testo = f"{num_fusti} steli (200x)"

    output = {
        "immagine_annotata": annotata,
        "eritema_diffuso": eritemi,
        "infiammazione_perifollicolare": 0,
        "tappi_sebacei": tappi,
        "follicoli_dormienti": follicoli_dormienti,
        "desquamazione_secca": 0,
        "sebo_ceroso": 0,
        "steli_anagen": steli_anagen,
        "steli_vellus": steli_vellus,
        "steli_nuovi": steli_nuovi,
        "spessori_um": spessori,
        "calibro_medio": calibro_m,
        "anisotropia": anisotropia,
        "densita_stimata": densita_val,
        "densita_testo": densita_testo,
        "note_auto": genera_referto_dermocosmetico(
            {
                "eritema_diffuso": eritemi,
                "sebo_ceroso": 0,
                "desquamazione_secca": 0,
                "tappi_sebacei": tappi,
                "infiammazione_perifollicolare": 0,
                "follicoli_dormienti": follicoli_dormienti,
                "calibro_medio": calibro_m,
                "anisotropia": anisotropia,
                "steli_nuovi": steli_nuovi,
                "steli_vellus": steli_vellus,
            },
            lente,
            luce,
            zona,
            parametri_cliente,
        ),
    }
    return output


# ============================================================================
# MOTORE VISION AI IBRIDO (RELAZIONE SINTETICA ESATTAMENTE DI 8-9 RIGHE)
# ============================================================================
def esegui_perizia_vision_ai(
    img_bgr,
    api_key,
    provider_scelto,
    modello_da_usare,
    dati_misurati,
    sesso,
    scala,
    zona,
    ottica,
    luce,
    sintomi_lista,
):
    prompt_sistema = f"""
Sei il Direttore Scientifico e Docente Internazionale di Dermo-Fitocosmetica e Tricoscopia Applicata (Standard S.I.Tri. e Metodo Righetti Since 1967).
Il tuo compito è redigere la RELAZIONE GLOBALE DI SINTESI per la pagina 2 del Report PDF.

REGOLE TASSATIVE DI FORMATTAZIONE:
1. Lunghezza totale: ESATTAMENTE 8-9 RIGHE COMPLESSIVE (non superare mai 10 righe).
2. Formattazione: NON usare asterischi markdown (NO **), solo testo semplice e pulito.
3. Spaziatura: I punti 1, 2 e 3 devono essere consecutivi andando SOLO a capo (NESSUNA riga vuota tra 1, 2 e 3).
4. Riga vuota di paragrafo: Inserisci una riga vuota SOLTANTO prima del punto 4.

DATI BIOMETRICI ACQUISITI:
- Paziente: {sesso} | Inquadramento: {scala}
- Area: {zona} | Ingrandimento: {ottica} | Luce: {luce}
- Sintomi riferiti: {', '.join(sintomi_lista) if sintomi_lista else 'Nessuno'}
- Parametri: Calibro {dati_misurati['calibro']} µm, Anisotropia {dati_misurati['anisotropia']}%, Densità {dati_misurati['densita']} cap/cm², Tappi sebacei {dati_misurati['tappi']}, Indice eritematoso {dati_misurati['eritemi']} focolai.

SCHEMA DI RISPOSTA OBBLIGATORIO (Rispetta esattamente questo ritmo di righe):
1. Inquadramento & Cute: [2 righe sullo stato del cuoio capelluto, grado di iperemia, idratazione, tensione e sebo]
2. Osti & Ancoraggio: [2 righe su pervietà ostiale, presenza di ipercheratosi, tappi sebacei e follicoli silenti]
3. Fusti & Densità: [2 righe su calibro medio, percentuale di anisotropia, miniaturizzazione e densità al cm²]

4. Protocollo Soluzione: Vedere PDF allegato "Rituale di Cura Domiciliare".
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
    }

    if "Groq" in provider_scelto:
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": modello_da_usare,
            "messages": [{"role": "user", "content": prompt_sistema}],
            "temperature": 0.2,
            "max_tokens": 500,
        }
    else:
        _, buffer = cv2.imencode(".jpg", img_bgr)
        img_base64 = base64.b64encode(buffer).decode("utf-8")
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": "gpt-4o",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_sistema},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_base64}"
                            },
                        },
                    ],
                }
            ],
            "temperature": 0.2,
            "max_tokens": 500,
        }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            contenuto = response.json()["choices"][0]["message"]["content"]
            return contenuto.replace("**", "").replace("###", "").strip()
        else:
            return f"Errore API ({response.status_code}): {response.text}"
    except Exception as e:
        return f"Errore di connessione: {str(e)}"


# ============================================================================
# SCHEDA CURA DOMICILIARE PDF (CON DENSITÀ + PROTOCOLLO SEQUENZIALE D'USO)
# ============================================================================
def genera_pdf_cura_domiciliare(
    nome_cliente,
    prodotti_assegnati,
    path_salvataggio,
    dati_confronto=None,
    protocollo_testo="",
):
    try:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        data_odierna = datetime.now().strftime("%d/%m/%Y")

        # 1. Header Istituzionale
        page.draw_rect(fitz.Rect(0, 0, 595, 130), color=None, fill=(0.12, 0.23, 0.38))
        page.insert_text(
            (50, 48),
            "RITUALE DI CURA DOMICILIARE",
            fontsize=18,
            color=(1, 1, 1),
            fontname="helv",
        )
        page.insert_text(
            (50, 72),
            "Studio Tricologico Righetti Since 1967",
            fontsize=12,
            color=(0.85, 0.92, 1),
            fontname="helv",
        )
        page.insert_text(
            (50, 105),
            f"Cliente: {nome_cliente}",
            fontsize=10.5,
            color=(1, 1, 1),
            fontname="helv",
        )
        page.insert_text(
            (380, 105),
            f"Data Check-up: {data_odierna}",
            fontsize=10.5,
            color=(1, 1, 1),
            fontname="helv",
        )

        y_pos = 150

        # 2. Sezione Comparativa a Due Colonne
        if dati_confronto:
            page.insert_text(
                (50, y_pos),
                "MONITORAGGIO EVOLUTIVO & RISPOSTA AL TRATTAMENTO",
                fontsize=12,
                color=(0.12, 0.23, 0.38),
                fontname="helv",
            )
            page.draw_line(
                fitz.Point(50, y_pos + 4),
                fitz.Point(545, y_pos + 4),
                color=(0.2, 0.4, 0.6),
                width=1.2,
            )
            y_pos += 12

            # Analisi e wrapping del testo AI
            giudizio_grezzo = str(dati_confronto.get("sintesi_ai", "")).strip()

            if "Rimodulare" in giudizio_grezzo or "Parziale" in giudizio_grezzo:
                colore_esito = (0.75, 0.15, 0.15)  # Rosso
                titolo_badge = (
                    "► GIUDIZIO DI EFFICACIA: RISPOSTA PARZIALE (DA RIMODULARE)"
                )
            elif "Stabile" in giudizio_grezzo or "stabilità" in giudizio_grezzo.lower():
                colore_esito = (0.75, 0.45, 0.05)  # Ambra
                titolo_badge = "► GIUDIZIO DI EFFICACIA: QUADRO STABILE"
            else:
                colore_esito = (0.08, 0.48, 0.18)  # Verde
                titolo_badge = "► GIUDIZIO DI EFFICACIA: RISPOSTA MOLTO FAVOREVOLE"

            parti = giudizio_grezzo.split("Giudizio di Efficacia:")
            corpo_relazione = (
                parti[0].replace("📊", "").replace("✅", "").replace("⚠️", "").strip()
            )
            testo_spiegazione = (
                parti[1].strip()
                if len(parti) > 1
                else "Riscontro positivo con rispetto dei parametri di incremento densità e calibro. Proseguire con il consolidamento."
            )

            for pref in [
                "Risposta terapeutico-cosmetica molto favorevole.",
                "Risposta parziale.",
                "Risposta terapeutico-cosmetica favorevole.",
            ]:
                if testo_spiegazione.startswith(pref):
                    testo_spiegazione = testo_spiegazione[len(pref) :].strip()

            righe_corpo = []
            for p in corpo_relazione.split("\n"):
                if p.strip():
                    righe_corpo.extend(textwrap.wrap(p.strip(), width=96))
            righe_spiegazione = textwrap.wrap(testo_spiegazione, width=96)

            interlinea = 11.0
            h_subbox_ai = 30 + (
                (len(righe_corpo) + len(righe_spiegazione) + 2) * interlinea
            )
            h_card_totale = 118 + h_subbox_ai + 12

            card_rect = fitz.Rect(50, y_pos, 545, y_pos + h_card_totale)
            page.draw_rect(card_rect, color=(0.75, 0.82, 0.90), fill=(0.98, 0.99, 1.0))

            # Parametri
            data_p = dati_confronto.get("data_prec", "Precedente")
            cal_p = dati_confronto.get("cal_p", 0.0)
            cal_a = dati_confronto.get("cal_a", 0.0)
            d_cal = dati_confronto.get("delta_cal", 0.0)
            p_cal = dati_confronto.get("perc_cal", 0.0)

            ani_p = dati_confronto.get("ani_p", 0.0)
            ani_a = dati_confronto.get("ani_a", 0.0)
            d_ani = dati_confronto.get("delta_ani", 0.0)

            den_p = dati_confronto.get("den_p", 0)
            den_a = dati_confronto.get("den_a", 0)
            d_den = dati_confronto.get("delta_den", 0)
            p_den = dati_confronto.get("perc_den", 0.0)

            tap_p = dati_confronto.get("tap_p", 0)
            tap_a = dati_confronto.get("tap_a", 0)
            d_tap = dati_confronto.get("delta_tap", 0)

            cura_prec = dati_confronto.get("prodotti_prec", "Protocollo iniziale")
            tempo_tr = dati_confronto.get("tempo_trascorso", "Periodo di controllo")

            # Colonna Sinistra: Visita Precedente
            col_sx_rect = fitz.Rect(58, y_pos + 8, 285, y_pos + 112)
            page.draw_rect(
                col_sx_rect, color=(0.82, 0.85, 0.88), fill=(0.94, 0.95, 0.96)
            )
            page.insert_text(
                (66, y_pos + 22),
                f"VISITA PRECEDENTE ({data_p})",
                fontsize=9.5,
                color=(0.3, 0.35, 0.4),
                fontname="helv",
            )
            page.insert_text(
                (66, y_pos + 38),
                f"• Calibro Medio: {cal_p} µm",
                fontsize=8.5,
                color=(0.2, 0.2, 0.2),
                fontname="helv",
            )
            page.insert_text(
                (66, y_pos + 52),
                f"• Anisotropia: {ani_p} %",
                fontsize=8.5,
                color=(0.2, 0.2, 0.2),
                fontname="helv",
            )
            page.insert_text(
                (66, y_pos + 66),
                f"• Densita: {den_p} capelli/cm2",
                fontsize=8.5,
                color=(0.2, 0.2, 0.2),
                fontname="helv",
            )
            page.insert_text(
                (66, y_pos + 80),
                f"• Tappi Sebacei: {tap_p}",
                fontsize=8.5,
                color=(0.2, 0.2, 0.2),
                fontname="helv",
            )
            cura_short = (cura_prec[:28] + "..") if len(cura_prec) > 28 else cura_prec
            page.insert_text(
                (66, y_pos + 95),
                f"• Cura: {cura_short}",
                fontsize=8.5,
                color=(0.4, 0.4, 0.4),
                fontname="helv",
            )

            # Colonna Destra: Visita Odierna
            col_dx_rect = fitz.Rect(310, y_pos + 8, 537, y_pos + 112)
            page.draw_rect(
                col_dx_rect, color=(0.70, 0.82, 0.95), fill=(0.92, 0.96, 1.0)
            )
            page.insert_text(
                (318, y_pos + 22),
                f"VISITA DI OGGI ({data_odierna})",
                fontsize=9.5,
                color=(0.12, 0.23, 0.38),
                fontname="helv",
            )

            sign_cal = "+" if d_cal > 0 else ""
            sign_ani = "+" if d_ani > 0 else ""
            sign_den = "+" if d_den > 0 else ""
            sign_tap = "+" if d_tap > 0 else ""

            page.insert_text(
                (318, y_pos + 38),
                f"• Calibro Medio: {cal_a} µm ({sign_cal}{d_cal} µm / {sign_cal}{p_cal}%)",
                fontsize=8.5,
                color=(0.1, 0.4, 0.1) if d_cal > 0 else (0.2, 0.2, 0.2),
                fontname="helv",
            )
            page.insert_text(
                (318, y_pos + 52),
                f"• Anisotropia: {ani_a} % ({sign_ani}{d_ani}%)",
                fontsize=8.5,
                color=(0.1, 0.4, 0.1) if d_ani < 0 else (0.2, 0.2, 0.2),
                fontname="helv",
            )
            page.insert_text(
                (318, y_pos + 66),
                f"• Densita: {den_a} cap/cm2 ({sign_den}{d_den} cap/cm2 / {sign_den}{p_den}%)",
                fontsize=8.5,
                color=(0.1, 0.4, 0.1) if d_den > 0 else (0.2, 0.2, 0.2),
                fontname="helv",
            )
            page.insert_text(
                (318, y_pos + 80),
                f"• Tappi Sebacei: {tap_a} ({sign_tap}{d_tap})",
                fontsize=8.5,
                color=(0.1, 0.4, 0.1) if d_tap < 0 else (0.2, 0.2, 0.2),
                fontname="helv",
            )
            page.insert_text(
                (318, y_pos + 95),
                f"• Tempo trascorso: {tempo_tr}",
                fontsize=8.5,
                color=(0.3, 0.35, 0.4),
                fontname="helv",
            )

            # Sub-box AI
            y_subbox_start = y_pos + 118
            ai_box_rect = fitz.Rect(
                58, y_subbox_start, 537, y_subbox_start + h_subbox_ai
            )
            page.draw_rect(ai_box_rect, color=(0.4, 0.6, 0.8), fill=(0.90, 0.94, 0.99))

            page.insert_text(
                (66, y_subbox_start + 14),
                "VALUTAZIONE COMPARATIVA & PROGRESSO CLINICO-COSMETICO:",
                fontsize=8.5,
                color=(0.12, 0.23, 0.38),
                fontname="helv",
            )

            y_riga = y_subbox_start + 28
            for riga in righe_corpo:
                page.insert_text(
                    (66, y_riga),
                    riga,
                    fontsize=7.8,
                    color=(0.18, 0.22, 0.30),
                    fontname="helv",
                )
                y_riga += interlinea

            y_riga += 4
            page.insert_text(
                (66, y_riga),
                titolo_badge,
                fontsize=8.2,
                color=colore_esito,
                fontname="helv",
            )
            y_riga += interlinea + 1

            for riga in righe_spiegazione:
                page.insert_text(
                    (66, y_riga),
                    riga,
                    fontsize=7.8,
                    color=(0.20, 0.24, 0.30),
                    fontname="helv",
                )
                y_riga += interlinea

            y_pos += h_card_totale + 22

        # -------------------------------------------------------------
        # 3. SEZIONE: PROTOCOLLO DI APPLICAZIONE & SEQUENZA D'USO
        # -------------------------------------------------------------
        if protocollo_testo and str(protocollo_testo).strip():
            if y_pos > 580:
                page = doc.new_page(width=595, height=842)
                y_pos = 50

            page.insert_text(
                (50, y_pos),
                "PROTOCOLLO DI APPLICAZIONE & SEQUENZA D'USO",
                fontsize=12,
                color=(0.12, 0.23, 0.38),
                fontname="hebo",
            )
            page.draw_line(
                fitz.Point(50, y_pos + 4),
                fitz.Point(545, y_pos + 4),
                color=(0.2, 0.4, 0.6),
                width=1.2,
            )
            y_pos += 12

            paragrafi_proto = [
                p.strip() for p in protocollo_testo.split("\n") if p.strip()
            ]

            # Calcolo preventivo altezza (inclusi i 2 stacchi paragrafo)
            linee_conteggio = 0
            for p in paragrafi_proto:
                wr = textwrap.wrap(p.replace("'", ""), width=94)
                linee_conteggio += len(wr)
                if "durata" in p.lower() or "dettaglio utilizzo" in p.lower():
                    linee_conteggio += 0.8

            interlinea_p = 12.5
            h_proto_box = 20 + (linee_conteggio * interlinea_p) + 8
            proto_rect = fitz.Rect(50, y_pos, 545, y_pos + h_proto_box)
            page.draw_rect(proto_rect, color=(0.78, 0.84, 0.90), fill=(0.96, 0.98, 1.0))

            y_riga_proto = y_pos + 15
            fs = 8.5
            colore_blu = (0.12, 0.23, 0.38)
            colore_nero = (0.20, 0.20, 0.20)

            for p in paragrafi_proto:
                is_durata = "durata" in p.lower()
                is_rinvio_tabella = (
                    "dettaglio utilizzo" in p.lower() or "per le dosi" in p.lower()
                )

                # Stacco di un paragrafo vuoto prima della Durata e prima della Nota finale
                if is_durata or is_rinvio_tabella:
                    y_riga_proto += 8

                # Caso 1: NOTA FINALE DI RINVIO (TUTTA IN BLU GRASSETTO)
                if is_rinvio_tabella:
                    righe_nota = textwrap.wrap(p, width=94)
                    for r_n in righe_nota:
                        page.insert_text(
                            (62, y_riga_proto),
                            r_n,
                            fontsize=fs,
                            color=colore_blu,
                            fontname="hebo",
                        )
                        y_riga_proto += interlinea_p

                # Caso 2: FASI CON TITOLO E SPIEGAZIONE
                elif ":" in p and (p.startswith("•") or p.startswith("-")):
                    parti_p = p.split(":", 1)
                    titolo_fase = parti_p[0].lstrip("•-").strip()
                    testo_spiegaz = ": " + parti_p[1].strip()

                    # Stampa Pallino in Nero
                    page.insert_text(
                        (62, y_riga_proto),
                        "• ",
                        fontsize=fs,
                        color=colore_nero,
                        fontname="helv",
                    )
                    w_bullet = fitz.get_text_length("• ", fontname="helv", fontsize=fs)

                    # Stampa Titolo Fase in BLU GRASSETTO
                    page.insert_text(
                        (62 + w_bullet, y_riga_proto),
                        titolo_fase,
                        fontsize=fs,
                        color=colore_blu,
                        fontname="hebo",
                    )
                    w_titolo = fitz.get_text_length(
                        titolo_fase, fontname="hebo", fontsize=fs
                    )

                    # Segmentazione nomi prodotti in BLU NORMALE
                    x_cursor = 62 + w_bullet + w_titolo
                    segmenti = re.split(r"('[\w\s\.-]+')", testo_spiegaz)

                    for seg in segmenti:
                        if not seg:
                            continue
                        is_prodotto = seg.startswith("'") and seg.endswith("'")
                        testo_stampa = seg.replace("'", "") if is_prodotto else seg
                        colore_curr = colore_blu if is_prodotto else colore_nero

                        parole_seg = testo_stampa.split()
                        for pw in parole_seg:
                            pw_spazio = pw + " "
                            w_pw = fitz.get_text_length(
                                pw_spazio, fontname="helv", fontsize=fs
                            )

                            if x_cursor + w_pw > 535:
                                y_riga_proto += interlinea_p
                                x_cursor = 62

                            page.insert_text(
                                (x_cursor, y_riga_proto),
                                pw_spazio,
                                fontsize=fs,
                                color=colore_curr,
                                fontname="helv",
                            )
                            x_cursor += w_pw

                    y_riga_proto += interlinea_p

                # Caso 3: Righe generiche
                else:
                    righe_std = textwrap.wrap(p, width=94)
                    for r_s in righe_std:
                        page.insert_text(
                            (62, y_riga_proto),
                            r_s,
                            fontsize=fs,
                            color=colore_nero,
                            fontname="helv",
                        )
                        y_riga_proto += interlinea_p

            y_pos += h_proto_box + 30

        # -------------------------------------------------------------
        # 4. SEZIONE: DETTAGLIO PRODOTTI (STACCATO ED ELEGANTE)
        # -------------------------------------------------------------
        if y_pos > 660:
            page = doc.new_page(width=595, height=842)
            y_pos = 50

        page.insert_text(
            (50, y_pos),
            "DETTAGLIO UTILIZZO PRODOTTI",
            fontsize=12,
            color=(0.12, 0.23, 0.38),
            fontname="hebo",
        )
        page.draw_line(
            fitz.Point(50, y_pos + 4),
            fitz.Point(545, y_pos + 4),
            color=(0.2, 0.4, 0.6),
            width=1.2,
        )
        y_pos += 20

        for idx, prod in enumerate(prodotti_assegnati, 1):
            if y_pos > 735:
                page = doc.new_page(width=595, height=842)
                y_pos = 50

            page.insert_text(
                (50, y_pos),
                f"{idx}. {prod['nome']}",
                fontsize=10.5,
                color=(0.12, 0.23, 0.38),
                fontname="helv",
            )
            y_pos += 14

            voci = [
                ("Categoria", prod.get("categoria")),
                (
                    "Modalita d'uso",
                    prod.get("modalita") or prod.get("modalita_default"),
                ),
                (
                    "Frequenza",
                    prod.get("frequenza") or prod.get("frequenza_default"),
                ),
                ("Orario", prod.get("orario") or prod.get("orario_default")),
                ("Dosi", prod.get("dosi")),
                ("Tempo di posa", prod.get("tempi_posa")),
                ("Durata trattamento", prod.get("durata_utilizzo")),
                ("Note", prod.get("note_utilizzo")),
            ]

            for label, valore in voci:
                if valore and str(valore).strip() and str(valore).strip() != "None":
                    page.insert_text(
                        (68, y_pos),
                        f"• {label}: {valore.strip()}",
                        fontsize=8.5,
                        color=(0.25, 0.25, 0.25),
                        fontname="helv",
                    )
                    y_pos += 12

            y_pos += 4
            page.draw_line(
                fitz.Point(50, y_pos),
                fitz.Point(545, y_pos),
                color=(0.88, 0.88, 0.88),
                width=0.5,
            )
            y_pos += 14

        # Footer
        page.insert_text(
            (50, 818),
            "Powered by @Righetti Since 1967",
            fontsize=8,
            color=(0.55, 0.55, 0.55),
            fontname="helv",
        )

        doc.save(path_salvataggio)
        doc.close()
        return True
    except Exception as e:
        st.error(f"Errore nella generazione scheda cura: {str(e)}")
        return False


# ============================================================================
# GENERAZIONE REPORT PDF MASTER (COMPRESSO A 3MB CON QUALITÀ CRISTALLINA)
# ============================================================================
def genera_pdf_righetti_completo(
    nome_cliente,
    eta,
    cellulare,
    email,
    nota_operatore,
    checkup_num,
    num_immagini,
    immagini_con_etichette,
    path_salvataggio,
    template_path="Report TricoCamera.pdf",
):
    if not os.path.exists(template_path):
        st.error(f"Template '{template_path}' non trovato!")
        return False

    try:
        doc = fitz.open(template_path)

        # -------------------------------------------------------------
        # PAGINA 1
        # -------------------------------------------------------------
        page1 = doc[0]
        widgets1 = page1.widgets()
        if widgets1:
            for widget in widgets1:
                if widget.field_name == "Nome e Cognome":
                    widget.field_value = str(nome_cliente)
                    widget.update()
                elif widget.field_name == "Num":
                    widget.field_value = str(eta)
                    widget.update()
                elif widget.field_name == "cell":
                    widget.field_value = str(cellulare)
                    widget.update()
                elif widget.field_name == "email":
                    widget.field_value = str(email)
                    widget.update()
                elif widget.field_name == "Date_af_date":
                    widget.field_value = datetime.now().strftime("%d/%m/%Y")
                    widget.update()

        # -------------------------------------------------------------
        # PAGINA 2: DATI CHECK-UP E NOTA DELL'OPERATORE
        # -------------------------------------------------------------
        page2 = doc[1]
        widgets2 = page2.widgets()
        if widgets2:
            for widget in widgets2:
                if widget.field_name == "Nome e Cognome":
                    widget.field_value = str(nome_cliente)
                    widget.update()
                elif widget.field_name == "Num":
                    widget.field_value = str(eta)
                    widget.update()
                elif widget.field_name == "cell":
                    widget.field_value = str(cellulare)
                    widget.update()
                elif widget.field_name == "email":
                    widget.field_value = str(email)
                    widget.update()
                elif widget.field_name == "Date_af_date":
                    widget.field_value = datetime.now().strftime("%d/%m/%Y")
                    widget.update()
                elif widget.field_name == "Date1_af_date":
                    widget.field_value = datetime.now().strftime("%d/%m/%Y")
                    widget.update()
                elif widget.field_name == "Text2":
                    widget.field_value = str(checkup_num)
                    widget.update()
                elif widget.field_name == "N1":
                    widget.field_value = str(num_immagini)
                    widget.update()
                elif widget.field_name == "N2":
                    widget.field_value = str(num_immagini)
                    widget.update()
                elif widget.field_name == "Text4":
                    testo_pulito_nota = str(nota_operatore or "").strip()
                    widget.field_value = testo_pulito_nota
                    widget.text_fontsize = 10
                    widget.update()

        # -------------------------------------------------------------
        # PAGINE 3-15: FOTO COMPRESSE IN JPG (RIDUZIONE PESO DA 150MB A 3MB)
        # -------------------------------------------------------------
        campi_pagine = {
            2: {"image": "Image1_af_image", "text": "Text5"},
            3: {"image": "Image2_af_image", "text": "Text6"},
            4: {"image": "Image3_af_image", "text": "Text7"},
            5: {"image": "Image4_af_image", "text": "Text8"},
            6: {"image": "Image5_af_image", "text": "Text9"},
            7: {"image": "Image6_af_image", "text": "Text10"},
            8: {"image": "Image7_af_image", "text": "Text11"},
            9: {"image": "Image8_af_image", "text": "Text12"},
            10: {"image": "Image9_af_image", "text": "Text13"},
            11: {"image": "Image10_af_image", "text": "Text14"},
            12: {"image": "Image11_af_image", "text": "Text15"},
            13: {"image": "Image12_af_image", "text": "Text16"},
            14: {"image": "Image13_af_image", "text": "Text17"},
        }

        for idx, img_data in enumerate(immagini_con_etichette):
            page_idx = min(2 + idx, 14)
            if page_idx in campi_pagine:
                page = doc[page_idx]
                campo_img = campi_pagine[page_idx]["image"]
                campo_text = campi_pagine[page_idx]["text"]
                widgets = page.widgets()
                if widgets:
                    for widget in widgets:
                        if widget.field_name == campo_img:
                            rect = widget.rect
                            img_rgb = img_data["immagine"]

                            # COMPRESSIONE JPEG 85% AL POSTO DEL PESANTE PNG
                            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                            img_bytes = cv2.imencode(
                                ".jpg",
                                img_bgr,
                                [int(cv2.IMWRITE_JPEG_QUALITY), 85],
                            )[1].tobytes()
                            page.insert_image(rect, stream=img_bytes)
                            break

                    for widget in widgets:
                        if widget.field_name == campo_text:
                            widget.field_value = str(img_data.get("note", "")).strip()
                            widget.text_fontsize = 8.5
                            widget.update()
                            break

        # SALVATAGGIO OTTIMIZZATO CON COMPRESSIONE DEFLATE
        doc.save(path_salvataggio, garbage=4, deflate=True, clean=True)
        doc.close()
        return True
    except Exception as e:
        st.error(f"Errore nella generazione PDF: {str(e)}")
        return False


# ============================================================================
# GENERATORE BOZZA PROTOCOLLO (CON RINVIO ALLA TABELLA IN CALCE)
# ============================================================================
def genera_bozza_protocollo_automatico(prodotti_assegnati):
    """Genera la sequenza logica del Rituale con rinvio finale alla tabella dettagli."""
    if not prodotti_assegnati:
        return "Nessun prodotto assegnato."

    fasi = []
    fase_num = 1

    # 1. Scrub Pre-Shampoo (LIQUET CUTIS)
    scrub_list = [
        p
        for p in prodotti_assegnati
        if "liquet" in p["nome"].lower() or "scrub" in p["nome"].lower()
    ]
    for s in scrub_list:
        fasi.append(
            f"• Fase {fase_num} (Esfoliazione Pre-Shampoo): Applicare '{s['nome']}' sul cuoio capelluto prima dello shampoo, massaggiare delicatamente emulsionando, quindi procedere al risciacquo."
        )
        fase_num += 1

    # 2. Detersione con Alternanza Shampoo
    shampoo_list = [
        p
        for p in prodotti_assegnati
        if "detergente" in str(p.get("categoria", "")).lower()
        or "sh." in p["nome"].lower()
        or "shampoo" in p["nome"].lower()
    ]

    if len(shampoo_list) >= 2:
        nomi_sh = ", ".join([f"'{sh['nome']}'" for sh in shampoo_list[:-1]])
        nomi_sh += f" e '{shampoo_list[-1]['nome']}'"
        fasi.append(
            f"• Fase {fase_num} (Detersione in Alternanza): Alternare ad ogni lavaggio {nomi_sh}, massaggiando delicatamente la cute con i polpastrelli prima del risciacquo con abbondante acqua tiepida."
        )
        fase_num += 1
    elif len(shampoo_list) == 1:
        fasi.append(
            f"• Fase {fase_num} (Detersione): Detergere con '{shampoo_list[0]['nome']}', massaggiando delicatamente la cute prima del risciacquo finale."
        )
        fase_num += 1

    # 3. Maschera Dermolenitiva Post-Shampoo (LUTUM CUTIS)
    lutum_list = [p for p in prodotti_assegnati if "lutum" in p["nome"].lower()]
    for m in lutum_list:
        fasi.append(
            f"• Fase {fase_num} (Argilla Dermolenitiva): Dopo lo shampoo distribuire '{m['nome']}' sul cuoio capelluto con il pennello, massaggiare leggermente, lasciare agire prima del risciacquo con acqua tiepida."
        )
        fase_num += 1

    # 4. Ristrutturante Fusto (UNGUENTUM CELLULARIS)
    unguentum_list = [
        p
        for p in prodotti_assegnati
        if "unguentum" in p["nome"].lower()
        or ("maschera" in p["nome"].lower() and "lutum" not in p["nome"].lower())
    ]
    for u in unguentum_list:
        fasi.append(
            f"• fase (Ricostruzione Cellulare): Dopo la detersione applicare '{u['nome']}' sul cuoio capelluto e massaggiare leggermente, lasciare agire prima di risciacquare accuratamente con acqua tiepida."
        )

    # 5. Trattamento Cute Leave-In (SPRAY / GOCCE POST-LAVAGGIO)
    topici_post = [
        p
        for p in prodotti_assegnati
        if (
            "spray" in p["nome"].lower()
            or "gocce" in p["nome"].lower()
            or "lozione" in p["nome"].lower()
        )
        and "liquet" not in p["nome"].lower()
    ]
    for t in topici_post:
        fasi.append(
            f"• Fase Leave-in (Senza Risciacquo): A capelli lavati e ben tamponati (o a cute asciutta), distribuire uniformemente '{t['nome']}' massaggiando leggermente, prima dell'asciugatura attendere 5 minuti."
        )

    # 6. Supporto Transdermico (CEROTTI POTENTIA)
    cerotti_list = [
        p
        for p in prodotti_assegnati
        if "cerot" in p["nome"].lower() or "patch" in p["nome"].lower()
    ]
    for c_item in cerotti_list:
        fasi.append(
            f"• Fase (Supporto Transdermico): Applicare il cerotto '{c_item['nome']}' sul polso o alla base del collo su cute pulita e asciutta."
        )

    # 7. Integrazione Funzionale
    integratori_list = [
        p
        for p in prodotti_assegnati
        if "integratore" in str(p.get("categoria", "")).lower()
        or "capsul" in p["nome"].lower()
    ]
    for integ in integratori_list:
        fasi.append(
            f"• Fase Integrazione Nutrizionale: Assumere '{integ['nome']}' al mattino con un bicchiere d'acqua."
        )

    # 8. Durata Ciclo (staccata)
    fasi.append(
        "• Durata del Ciclo: Seguire scrupolosamente il presente rituale per i primi 3/4 mesi, con controllo tricologico programmato al termine per la valutazione dei risultati."
    )

    # 9. Nota di Rinvio Tabella (staccata in blu grassetto)
    fasi.append(
        '• PER LE DOSI, TEMPI DI POSA E APPLICAZIONI, fare riferimento alla tabella sotto riportata: "DETTAGLIO UTILIZZO PRODOTTI".'
    )

    return "\n".join(fasi)


# ============================================================================
# GESTIONE CARTELLA MASTER "PERCORSI CLIENTI" - VERSIONE PER STREAMLIT CLOUD
# ============================================================================
def trova_o_crea_cartella_cliente(nome_cliente):
    """Trova o crea la cartella del cliente - ADATTATA PER STREAMLIT CLOUD"""
    
    # USA LA CARTELLA DEL PROGETTO (dove hai i permessi di scrittura)
    cartella_master = os.path.join(os.getcwd(), "PERCORSI CLIENTI")
    
    try:
        os.makedirs(cartella_master, exist_ok=True)
    except Exception:
        # Fallback: usa una cartella temporanea
        import tempfile
        cartella_master = os.path.join(tempfile.gettempdir(), "PERCORSI_CLIENTI")
        os.makedirs(cartella_master, exist_ok=True)
    
    if not nome_cliente or str(nome_cliente).strip() in ("", "-- Seleziona --"):
        return cartella_master
    
    # Parole del nome cercato (in minuscolo)
    parole_cercate = set(re.findall(r"\w+", str(nome_cliente).lower(), re.UNICODE))
    
    # Scansione intelligente delle cartelle già esistenti
    try:
        cartelle_esistenti = [
            d for d in os.listdir(cartella_master)
            if os.path.isdir(os.path.join(cartella_master, d))
        ]
        for cartella in cartelle_esistenti:
            parole_cartella = set(re.findall(r"\w+", str(cartella).lower(), re.UNICODE))
            if parole_cercate and parole_cartella and parole_cercate == parole_cartella:
                return os.path.join(cartella_master, cartella)
    except Exception:
        pass
    
    # Se è un nuovo cliente, crea la sua cartella
    nuova_cartella = os.path.join(cartella_master, str(nome_cliente).strip())
    os.makedirs(nuova_cartella, exist_ok=True)
    return nuova_cartella


# ============================================================================
# MOTORE COMPARATIVO AI: VALUTAZIONE PRIMA / DOPO
# ============================================================================
def genera_valutazione_comparativa_ai(
    dati_prec, dati_attuali, sesso, scala, prodotti_precedenti=""
):
    cal_p = dati_prec.get("calibro_medio", 0.0)
    cal_a = dati_attuali.get("calibro_medio", 0.0)
    ani_p = dati_prec.get("anisotropia", 0.0)
    ani_a = dati_attuali.get("anisotropia", 0.0)
    den_p = dati_prec.get("densita_f", 0) or dati_prec.get("densita", 0) or 0
    den_a = dati_attuali.get("densita_f", 0) or dati_attuali.get("densita", 0) or 0
    tap_p = dati_prec.get("tappi_sebacei", 0)
    tap_a = dati_attuali.get("tappi_sebacei", 0)
    eri_p = dati_prec.get("eritemi", 0)
    eri_a = dati_attuali.get("eritemi", 0)
    nuo_a = dati_attuali.get("steli_nuovi", 0)

    delta_cal = round(cal_a - cal_p, 1) if (cal_p > 0 and cal_a > 0) else 0.0
    delta_ani = round(ani_a - ani_p, 1) if (ani_p > 0 and ani_a > 0) else 0.0
    delta_den = den_a - den_p
    delta_tap = tap_a - tap_p

    commenti = []
    efficacia = "Positiva"

    # 1. Valutazione Densità (Parametro Garanzia Studio)
    if delta_den > 10:
        commenti.append(
            f"incremento netto della densità (+{delta_den} capelli/cm²), a conferma della riattivazione follicolare"
        )
    elif delta_den < -10:
        commenti.append(f"flessione della densità ({delta_den} capelli/cm²)")
        efficacia = "Rimodulare"
    else:
        commenti.append(
            f"mantenimento e stabilità della densità follicolare ({den_a} capelli/cm²)"
        )

    # 2. Valutazione Calibro
    if delta_cal > 2.0:
        commenti.append(f"incremento del calibro medio (+{delta_cal} µm)")
    elif delta_cal < -2.0:
        commenti.append(f"assottigliamento degli steli ({delta_cal} µm)")

    # 3. Valutazione Anisotropia
    if delta_ani < -3.0:
        commenti.append(
            f"riduzione dell'anisotropia ({delta_ani}%), con maggiore uniformità dei fusti"
        )

    # 4. Osti e Ricrescita
    if delta_tap < 0:
        commenti.append(
            f"risoluzione dei tappi sebacei ({abs(delta_tap)} osti liberati)"
        )
    if nuo_a > 0:
        commenti.append(f"{nuo_a} nuovi germogli anagen in ricrescita")

    data_prec = dati_prec.get("data", "visita precedente")
    testo = f"📊 RELAZIONE COMPARATIVA DI CONTROLLO (vs Check-up {data_prec}):\n"
    testo += (
        f"Paziente: {sesso} | Inquadramento: {scala}.\n"
        f"A seguito del protocollo di cura domiciliare precedentemente impostato"
    )
    if prodotti_precedenti:
        testo += f" ({prodotti_precedenti})"
    testo += (
        f", l'esame tricoscopico odierno evidenzia: " + "; ".join(commenti) + ".\n\n"
    )

    if efficacia == "Positiva":
        testo += "✅ Giudizio di Efficacia: Risposta terapeutico-cosmetica molto favorevole con rispetto dei parametri di incremento densità. Proseguire con il consolidamento."
    else:
        testo += "⚠️ Giudizio di Efficacia: Risposta parziale. Si raccomanda di intensificare la stimolazione topica per supportare la densità follicolare."

    return {
        "testo": testo,
        "delta_cal": delta_cal,
        "delta_ani": delta_ani,
        "delta_den": delta_den,
        "delta_tap": delta_tap,
        "efficacia": efficacia,
    }


# ============================================================================
# RICONOSCIMENTO AUTOMATICO GENERE (UOMO / DONNA) DAL NOME
# ============================================================================
def deduci_sesso_da_nome(nome_completo):
    """Riconosce automaticamente se il cliente è Uomo o Donna in base al nome."""
    if not nome_completo:
        return "Uomo"

    primo_nome = (
        str(nome_completo).strip().split()[0].replace("'", "").replace("-", "").lower()
    )

    # Eccezioni maschili che finiscono in 'a' o consonante
    maschili_speciali = {
        "andrea",
        "luca",
        "mattia",
        "nicola",
        "elia",
        "gianluca",
        "gianandrea",
        "pierluca",
        "battista",
        "sasha",
        "christian",
        "omar",
        "radouan",
        "israel",
        "walter",
        "manuel",
        "ethan",
        "nikolo",
        "lendmir",
        "sergio",
        "davide",
        "simone",
        "michele",
        "daniele",
        "gabriele",
        "emanuele",
        "raffaele",
        "samuele",
        "achille",
        "ettore",
        "cesare",
        "giuseppe",
    }

    # Eccezioni femminili che non finiscono in 'a'
    femminili_speciali = {
        "alice",
        "beatrice",
        "irene",
        "matilde",
        "adele",
        "noemi",
        "carmen",
        "miriam",
        "rachel",
        "esther",
        "zoe",
        "cloe",
        "nicole",
        "agape",
    }

    if primo_nome in maschili_speciali:
        return "Uomo"
    if primo_nome in femminili_speciali:
        return "Donna"

    # Regola generale sulle vocali
    if primo_nome.endswith("a"):
        return "Donna"
    else:
        return "Uomo"


# ============================================================================
# SINCRONIZZAZIONE GOOGLE SHEETS (CON SCARICAMENTO PROTETTO DA ERRORI SSL)
# ============================================================================
import io
import ssl
import urllib.request


def sincronizza_google_sheets(sheet_url, conn):
    """Legge il foglio Google Sheets superando il blocco SSL di macOS."""
    try:
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", sheet_url)
        if not match:
            return (
                False,
                "Link di Google Sheets non valido. Assicurati che contenga '/d/ID_FOGLIO/'.",
            )

        sheet_id = match.group(1)
        export_url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
        )

        # Supera il blocco certificati SSL su Mac
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            csv_bytes = resp.read()

        df_gs = pd.read_csv(io.BytesIO(csv_bytes))
        df_gs.columns = [str(c).strip().upper() for c in df_gs.columns]

        col_nome = next(
            (c for c in df_gs.columns if "NOME" in c or "CLIENTE" in c), None
        )
        col_cell = next(
            (c for c in df_gs.columns if "CELL" in c or "TEL" in c or "TELEFONO" in c),
            None,
        )
        col_email = next(
            (c for c in df_gs.columns if "EMAIL" in c or "MAIL" in c), None
        )

        if not col_nome:
            return (
                False,
                "Colonna 'NOME E COGNOME' non trovata nella prima riga del foglio.",
            )

        c = conn.cursor()
        nuovi = 0
        aggiornati = 0

        for _, row in df_gs.iterrows():
            nome_val = str(row[col_nome]).strip() if pd.notna(row[col_nome]) else ""
            if not nome_val or nome_val.lower() == "nan":
                continue

            cell_val = (
                str(row[col_cell]).replace(".0", "").strip()
                if (col_cell and pd.notna(row[col_cell]))
                else ""
            )
            email_val = (
                str(row[col_email]).strip()
                if (col_email and pd.notna(row[col_email]))
                else ""
            )

            # Riconoscimento automatico del genere dal nome
            sesso_dedotto = deduci_sesso_da_nome(nome_val)

            res = c.execute(
                "SELECT id FROM clienti WHERE codice_cliente = ?", (nome_val,)
            ).fetchone()
            if res:
                c.execute(
                    "UPDATE clienti SET cellulare = ?, email = ? WHERE id = ?",
                    (cell_val, email_val, res[0]),
                )
                aggiornati += 1
            else:
                c.execute(
                    "INSERT INTO clienti (codice_cliente, cellulare, email, sesso) VALUES (?, ?, ?, ?)",
                    (nome_val, cell_val, email_val, sesso_dedotto),
                )
                nuovi += 1

        conn.commit()
        return (
            True,
            f"✅ Sincronizzazione completata! {nuovi} nuovi clienti aggiunti, {aggiornati} anagrafiche aggiornate.",
        )
    except Exception as e:
        return (
            False,
            f"Errore durante la lettura di Google Sheets: {e}. Assicurati che il foglio sia condiviso con 'Chiunque abbia il link può visualizzare'.",
        )


# ============================================================================
# CALCOLO PROGRESSIVO AUTOMATICO DEI FILE SU DISCO (REPORT, CURA, DASHBOARD)
# ============================================================================
def calcola_prefisso_da_file_esistenti(cartella_cliente_path, tipo_documento):
    """Controlla i PDF già presenti nella cartella e calcola il prefisso corretto ('', '2° ', '3° '...)."""
    try:
        if not os.path.exists(cartella_cliente_path):
            return ""

        files = os.listdir(cartella_cliente_path)
        t_low = str(tipo_documento).lower()

        # Identifica esattamente il tipo di file cercato
        if "report" in t_low:
            parola_chiave = "Report Tricologico"
        elif "rituale" in t_low or "cura" in t_low:
            parola_chiave = "Rituale di Cura"
        elif "dashboard" in t_low or "grafic" in t_low:
            parola_chiave = "Dashboard Grafici"
        else:
            parola_chiave = tipo_documento

        # Filtra tutti i PDF di quel tipo presenti nella cartella
        pdf_trovati = [
            f
            for f in files
            if f.lower().endswith(".pdf") and parola_chiave.lower() in f.lower()
        ]

        if not pdf_trovati:
            return ""

        # Trova il numero progressivo più alto già presente
        max_num = 1
        for f_name in pdf_trovati:
            match = re.search(r"(\d+)\s*°", f_name)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
            else:
                # Se esiste già il file base senza numero (es. "Nome | Dashboard Grafici.pdf")
                if max_num < 1:
                    max_num = 1

        return f"{max_num + 1}° "
    except Exception:
        return ""


# ============================================================================
# FORMATTAZIONE DATE UNIVERSALE IN FORMATO ITALIANO (GG/MM/AAAA)
# ============================================================================
def formatta_data_it(val_data, con_ora=True):
    """Converte qualsiasi data nel formato italiano pulito (es. 31/08/2026 21:56)."""
    if not val_data or str(val_data).strip() == "" or str(val_data) == "None":
        return datetime.now().strftime("%d/%m/%Y %H:%M" if con_ora else "%d/%m/%Y")

    val_pulito = str(val_data).strip().split(".")[0]
    formati_da_provare = (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%m-%Y %H:%M",
    )

    for fmt in formati_da_provare:
        try:
            dt = datetime.strptime(val_pulito, fmt)
            return dt.strftime("%d/%m/%Y %H:%M" if con_ora else "%d/%m/%Y")
        except ValueError:
            pass

    return str(val_data)


# ============================================================================
# GENERATORE PDF DASHBOARD CON GRIGLIA 2x2 IDENTICA AL SOFTWARE (CON TAPPI ED ERITEMI)
# ============================================================================
import io
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def genera_pdf_dashboard_grafici(
    nome_cliente, df_trend, ultima_visita, path_salvataggio
):
    try:
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        data_odierna = datetime.now().strftime("%d/%m/%Y")
        data_ultima_it = formatta_data_it(ultima_visita["data"], con_ora=False)

        # 1. Header Istituzionale
        page.draw_rect(fitz.Rect(0, 0, 595, 120), color=None, fill=(0.12, 0.23, 0.38))
        page.insert_text(
            (50, 42),
            "DASHBOARD GRAFICI & MONITORAGGIO BIOMETRICO",
            fontsize=16,
            color=(1, 1, 1),
            fontname="helv",
        )
        page.insert_text(
            (50, 65),
            "Studio Tricologico Righetti Since 1967",
            fontsize=12,
            color=(0.85, 0.92, 1),
            fontname="helv",
        )
        page.insert_text(
            (50, 94),
            f"Cliente: {nome_cliente}",
            fontsize=10,
            color=(1, 1, 1),
            fontname="helv",
        )
        page.insert_text(
            (380, 94),
            f"Data Report: {data_odierna}",
            fontsize=10,
            color=(1, 1, 1),
            fontname="helv",
        )

        y_pos = 135

        # -------------------------------------------------------------
        # 2. GRAFICO 1: COMPOSIZIONE FASCE DI CALIBRO (CIAMBELLA)
        # -------------------------------------------------------------
        page.insert_text(
            (50, y_pos),
            f"1. COMPOSIZIONE STRUTTURALE DEI FUSTI (Check-up del {data_ultima_it})",
            fontsize=10.5,
            color=(0.12, 0.23, 0.38),
            fontname="helv",
        )
        page.draw_line(
            fitz.Point(50, y_pos + 4),
            fitz.Point(545, y_pos + 4),
            color=(0.2, 0.4, 0.6),
            width=1,
        )
        y_pos += 10

        cal_val = float(ultima_visita["calibro_medio"] or 0)
        ani_val = float(ultima_visita["anisotropia"] or 0)
        vellus_pct = float(ultima_visita["perc_vellus"] or 0)
        quota_vellus = vellus_pct if vellus_pct > 0 else (4.0 if ani_val > 15 else 1.0)

        if cal_val >= 75.0:
            quota_robusti = max(10.0, 75.0 - (ani_val * 1.2))
            quota_medi = max(10.0, 20.0 + (ani_val * 0.8))
            quota_sottili = max(2.0, 100.0 - quota_robusti - quota_medi - quota_vellus)
        elif cal_val >= 55.0:
            quota_robusti = max(5.0, 35.0 - (ani_val * 0.8))
            quota_medi = 45.0
            quota_sottili = max(5.0, 100.0 - quota_robusti - quota_medi - quota_vellus)
        else:
            quota_robusti = 5.0
            quota_medi = 25.0
            quota_sottili = max(10.0, 70.0 - quota_vellus)

        labels_fasce = [
            f"Terminali Robusti >70µm ({quota_robusti:.1f}%)",
            f"Fusti Medi 50-70µm ({quota_medi:.1f}%)",
            f"Fusti Sottili 35-50µm ({quota_sottili:.1f}%)",
            f"Vellus <35µm ({quota_vellus:.1f}%)",
        ]
        values_fasce = [quota_robusti, quota_medi, quota_sottili, quota_vellus]
        colors_fasce = ["#1E7E34", "#2E86AB", "#F39C12", "#E74C3C"]

        def formatta_pct_fetta(pct):
            return f"{pct:.1f}%" if pct >= 3.0 else ""

        fig_pie, ax_pie = plt.subplots(figsize=(6.5, 2.4))
        wedges, texts, autotexts = ax_pie.pie(
            values_fasce,
            colors=colors_fasce,
            startangle=90,
            autopct=formatta_pct_fetta,
            pctdistance=0.74,
            wedgeprops=dict(width=0.45, edgecolor="white", linewidth=2),
        )

        for at in autotexts:
            at.set_color("white")
            at.set_fontsize(8)
            at.set_fontweight("bold")

        ax_pie.legend(
            wedges,
            labels_fasce,
            loc="center left",
            bbox_to_anchor=(0.96, 0.5),
            fontsize=8,
            frameon=False,
        )
        ax_pie.axis("equal")
        plt.tight_layout()

        buf_pie = io.BytesIO()
        plt.savefig(buf_pie, format="png", dpi=180, bbox_inches="tight")
        plt.close(fig_pie)
        buf_pie.seek(0)

        page.insert_image(fitz.Rect(50, y_pos, 545, y_pos + 130), stream=buf_pie.read())
        y_pos += 140

        # -------------------------------------------------------------
        # 3. GRAFICI 2x2 IDENTICI AL SOFTWARE (SE CI SONO 2+ VISITE)
        # -------------------------------------------------------------
        if len(df_trend) >= 2:
            page.insert_text(
                (50, y_pos),
                "2. CURVE DI RISPOSTA & MONITORAGGIO NEL TEMPO (Check-up a Confronto)",
                fontsize=10.5,
                color=(0.12, 0.23, 0.38),
                fontname="helv",
            )
            page.draw_line(
                fitz.Point(50, y_pos + 4),
                fitz.Point(545, y_pos + 4),
                color=(0.2, 0.4, 0.6),
                width=1,
            )
            y_pos += 10

            date_x = [formatta_data_it(d, con_ora=False) for d in df_trend["data"]]
            x_indices = np.arange(len(date_x))

            # Creazione Griglia 2x2 ad alta definizione
            fig_grid, ((ax_den, ax_cal), (ax_ani, ax_bar)) = plt.subplots(
                2, 2, figsize=(10, 6.4)
            )

            # --- SUBPLOT 1: DENSITÀ (Verde) ---
            ax_den.plot(
                date_x,
                df_trend["densita_f"],
                marker="o",
                color="#1E7E34",
                linewidth=2.8,
                markersize=7,
            )
            ax_den.set_title(
                "Evoluzione DENSITÀ (capelli/cm²)",
                fontsize=9,
                fontweight="bold",
                pad=8,
            )
            ax_den.set_ylabel("capelli / cm²", fontsize=7.5, color="#555")
            for x_idx, val in enumerate(df_trend["densita_f"]):
                ax_den.annotate(
                    f"{val}",
                    (x_idx, val),
                    xytext=(0, 6),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                    fontweight="bold",
                    color="#1E7E34",
                )
            ax_den.grid(axis="y", linestyle="--", alpha=0.4, color="#d0d7de")
            ax_den.spines["top"].set_visible(False)
            ax_den.spines["right"].set_visible(False)
            ax_den.tick_params(axis="both", labelsize=7.5)

            # --- SUBPLOT 2: CALIBRO MEDIO (Blu) ---
            ax_cal.plot(
                date_x,
                df_trend["calibro_medio"],
                marker="o",
                color="#2E86AB",
                linewidth=2.8,
                markersize=7,
            )
            ax_cal.set_title(
                "Evoluzione CALIBRO MEDIO (µm)",
                fontsize=9,
                fontweight="bold",
                pad=8,
            )
            ax_cal.set_ylabel("Micron (µm)", fontsize=7.5, color="#555")
            for x_idx, val in enumerate(df_trend["calibro_medio"]):
                ax_cal.annotate(
                    f"{val}",
                    (x_idx, val),
                    xytext=(0, 6),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                    fontweight="bold",
                    color="#2E86AB",
                )
            ax_cal.grid(axis="y", linestyle="--", alpha=0.4, color="#d0d7de")
            ax_cal.spines["top"].set_visible(False)
            ax_cal.spines["right"].set_visible(False)
            ax_cal.tick_params(axis="both", labelsize=7.5)

            # --- SUBPLOT 3: ANISOTROPIA % (Rosso) ---
            ax_ani.plot(
                date_x,
                df_trend["anisotropia"],
                marker="o",
                color="#E74C3C",
                linewidth=2.8,
                markersize=7,
            )
            ax_ani.set_title(
                "Trend ANISOTROPIA % (Miniaturizzazione)",
                fontsize=9,
                fontweight="bold",
                pad=8,
            )
            ax_ani.set_ylabel("Anisotropia %", fontsize=7.5, color="#555")
            for x_idx, val in enumerate(df_trend["anisotropia"]):
                ax_ani.annotate(
                    f"{val}%",
                    (x_idx, val),
                    xytext=(0, 6),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                    fontweight="bold",
                    color="#E74C3C",
                )
            ax_ani.grid(axis="y", linestyle="--", alpha=0.4, color="#d0d7de")
            ax_ani.spines["top"].set_visible(False)
            ax_ani.spines["right"].set_visible(False)
            ax_ani.tick_params(axis="both", labelsize=7.5)

            # --- SUBPLOT 4: TAPPI ED ERITEMI (Istogramma Raggruppato) ---
            w_bar = 0.28
            bar_tappi = ax_bar.bar(
                x_indices - w_bar / 2,
                df_trend["osti_intasati"],
                width=w_bar,
                label="Tappi Sebacei",
                color="#F39C12",
            )
            bar_eri = ax_bar.bar(
                x_indices + w_bar / 2,
                df_trend["eritemi"],
                width=w_bar,
                label="Indice Eritema",
                color="#C0392B",
            )
            ax_bar.set_title(
                "Trend Ipercheratosi Ostiale & Infiammazione",
                fontsize=9,
                fontweight="bold",
                pad=8,
            )
            ax_bar.set_xticks(x_indices)
            ax_bar.set_xticklabels(date_x, fontsize=7.5)
            ax_bar.legend(loc="upper right", fontsize=7.5, frameon=False)
            ax_bar.grid(axis="y", linestyle="--", alpha=0.4, color="#d0d7de")
            ax_bar.spines["top"].set_visible(False)
            ax_bar.spines["right"].set_visible(False)
            ax_bar.tick_params(axis="both", labelsize=7.5)

            for b in bar_tappi:
                val = b.get_height()
                if val > 0:
                    ax_bar.annotate(
                        f"{int(val)}",
                        (b.get_x() + b.get_width() / 2, val),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7,
                        color="#B87708",
                        fontweight="bold",
                    )
            for b in bar_eri:
                val = b.get_height()
                if val > 0:
                    ax_bar.annotate(
                        f"{int(val)}",
                        (b.get_x() + b.get_width() / 2, val),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7,
                        color="#962215",
                        fontweight="bold",
                    )

            plt.tight_layout(h_pad=2.2, w_pad=2.2)
            buf_grid = io.BytesIO()
            plt.savefig(buf_grid, format="png", dpi=200, bbox_inches="tight")
            plt.close(fig_grid)
            buf_grid.seek(0)

            # Inserimento Griglia 2x2
            page.insert_image(
                fitz.Rect(50, y_pos, 545, y_pos + 380), stream=buf_grid.read()
            )
            y_pos += 390
        else:
            box_info = fitz.Rect(50, y_pos, 545, y_pos + 65)
            page.draw_rect(box_info, color=(0.75, 0.82, 0.90), fill=(0.95, 0.97, 1.0))
            page.insert_text(
                (65, y_pos + 25),
                "MONITORAGGIO EVOLUTIVO TEMPORALE:",
                fontsize=9.5,
                color=(0.12, 0.23, 0.38),
                fontname="helv",
            )
            page.insert_text(
                (65, y_pos + 45),
                "Le 4 curve comparative (Densità, Calibro, Anisotropia, Tappi ed Eritemi) si genereranno al 2° check-up.",
                fontsize=8.5,
                color=(0.3, 0.3, 0.3),
                fontname="helv",
            )
            y_pos += 80

        # Footer
        page.insert_text(
            (50, 818),
            "Powered by @Righetti Since 1967",
            fontsize=8,
            color=(0.55, 0.55, 0.55),
            fontname="helv",
        )

        doc.save(path_salvataggio, garbage=4, deflate=True, clean=True)
        doc.close()
        return True
    except Exception as e:
        st.error(f"Errore nella generazione Dashboard PDF: {str(e)}")
        return False


# ============================================================================
# MOTORE PRESCRIZIONE AI RIGHETTI (LETTURA COMPLETA INCI, DESCRIZIONI E DOSI)
# ============================================================================
def auto_assegna_trattamento_righetti(cl_id, conn, sintomi_dict):
    """Analizza le anomalie della visita, gli INCI e le descrizioni dei prodotti assegnando la cura su misura."""
    c = conn.cursor()

    # 1. Svuota la lista precedente per ripartire da zero
    c.execute("DELETE FROM prodotti_cliente WHERE cliente_id = ?", (cl_id,))

    # 2. Recupera i dati biometrici della visita odierna
    an_rec = c.execute(
        """
        SELECT calibro_medio, anisotropia, densita_f, osti_intasati, eritemi, steli_nuovi
        FROM analisi WHERE cliente_id = ? ORDER BY id DESC LIMIT 1
    """,
        (cl_id,),
    ).fetchone()

    if an_rec:
        cal_m = float(an_rec[0] or 75.0)
        ani_m = float(an_rec[1] or 12.0)
        tot_tappi = int(an_rec[3] or 0)
        tot_eritemi = int(an_rec[4] or 0)
    else:
        cal_m = 75.0
        ani_m = 12.0
        tot_tappi = 0
        tot_eritemi = 0

    chk_prurito = sintomi_dict.get("prurito", False)
    chk_dolore = sintomi_dict.get("dolore", False)
    chk_caduta = sintomi_dict.get("caduta_abbondante", False)
    chk_sebo = sintomi_dict.get("sebo_eccesso", False)
    quadro = sintomi_dict.get("quadro_ipotesi", "Standard")

    nomi_prodotti_target = []

    # -------------------------------------------------------------
    # FASE 1: ESFOLIAZIONE PRE-SHAMPOO (LIQUET vs LUTUM)
    # -------------------------------------------------------------
    # Se la microcamera rileva tappi sebacei, sebo o ipercheratosi ostiale -> LIQUET CUTIS
    if tot_tappi > 0 or chk_sebo:
        nomi_prodotti_target.append("LIQUET CUTIS 100ML")

    # Se c'è infiammazione/flogosi o prurito -> Maschera detox LUTUM CUTIS
    if tot_eritemi > 1 or chk_prurito or chk_dolore:
        nomi_prodotti_target.append("LUTUM CUTIS 250ML")

    # -------------------------------------------------------------
    # FASE 2: DETERSIONE (MINIMO 2 SHAMPOO DA ALTERNARE)
    # -------------------------------------------------------------
    shampoo_selezionati = []

    # Shampoo Specifici in base alle anomalie rilevate
    if tot_tappi > 1 or chk_sebo or "Seborroico" in quadro:
        shampoo_selezionati.append("SH. COMPENSATIO 300ML")
    if "Pitiriasi" in quadro or "Desquamazione" in quadro or chk_prurito:
        shampoo_selezionati.append("SH. PURGATIO 300ML")
    if ani_m > 18.0 or "Androgenetica" in quadro or chk_caduta:
        shampoo_selezionati.append("SH. FORTIS 300ML")
    if cal_m < 55.0 or chk_dolore:
        shampoo_selezionati.append("SH. POTENTIA 300ML")

    # Se è stato individuato solo 1 shampoo specifico, abbina il 2° shampoo complementare
    if len(shampoo_selezionati) == 1:
        if (
            "COMPENSATIO" in shampoo_selezionati[0]
            or "PURGATIO" in shampoo_selezionati[0]
        ):
            shampoo_selezionati.append("SH. REPARATOR CELLULARIS 300ML")
        else:
            shampoo_selezionati.append("SH. REPARATOR CELLULARIS 300ML")
    elif len(shampoo_selezionati) == 0:
        # Se non ci sono anomalie gravi, abbina i due shampoo di mantenimento e trofismo
        shampoo_selezionati.append("SH. REPARATOR CELLULARIS 300ML")
        shampoo_selezionati.append("SH. FORTIS 300ML")

    for sh_nome in shampoo_selezionati:
        nomi_prodotti_target.append(sh_nome)

    # -------------------------------------------------------------
    # FASE 3: TRATTAMENTO CUTE POST-LAVAGGIO (SPRAY / GOCCE - NO LIQUET)
    # -------------------------------------------------------------
    if ani_m > 20.0 or "Androgenetica" in quadro:
        nomi_prodotti_target.append("GOCCE POTENTIA 100ML")
        nomi_prodotti_target.append("SPRAY FORTIS 100ML")
    elif tot_tappi > 0 or chk_sebo or chk_prurito:
        nomi_prodotti_target.append("SPRAY PURGATIO 100ML")
    else:
        nomi_prodotti_target.append("SPRAY FORTIS 100ML")

    # -------------------------------------------------------------
    # FASE 4: MASCHERA RISTRUTTURANTE FUSTO (UNGUENTUM)
    # -------------------------------------------------------------
    if cal_m < 60.0 or ani_m > 14.0:
        nomi_prodotti_target.append("UNGUENTUM CELLULARIS 300ML")

    # -------------------------------------------------------------
    # FASE 5: SUPPORTO TRANSDERMICO (CEROTTI)
    # -------------------------------------------------------------
    if chk_caduta or "Effluvio" in quadro or ani_m > 18.0:
        nomi_prodotti_target.append("CEROTUM POTENTIA")

    # Inserimento nel database ereditando esattamente dosi, tempi e descrizioni dal tuo catalogo
    n_assegnati = 0
    for p_target in nomi_prodotti_target:
        res_prod = c.execute(
            """
            SELECT id, modalita, frequenza, orario, dosi, tempi_posa, durata_utilizzo, note 
            FROM prodotti WHERE nome LIKE ?
        """,
            (f"%{p_target.strip()}%",),
        ).fetchone()

        if res_prod:
            (
                p_id,
                p_mod,
                p_freq,
                p_ora,
                p_dosi,
                p_posa,
                p_dur,
                p_note,
            ) = res_prod
            c.execute(
                """
                INSERT INTO prodotti_cliente 
                (cliente_id, prodotto_id, modalita, frequenza, orario, dosi, tempi_posa, durata_utilizzo, note_utilizzo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    cl_id,
                    p_id,
                    str(p_mod or ""),
                    str(p_freq or ""),
                    str(p_ora or ""),
                    str(p_dosi or ""),
                    str(p_posa or ""),
                    str(p_dur or ""),
                    str(p_note or ""),
                ),
            )
            n_assegnati += 1

    conn.commit()
    return n_assegnati

# ============================================================================
# RECUPERO CATALOGO PRODOTTI DA SUPABASE
# ============================================================================
@st.cache_data(ttl=60)
def get_catalogo_prodotti():
    """Recupera il catalogo prodotti da Supabase"""
    if supabase:
        try:
            res = supabase.table("prodotti").select("*").order("categoria").order("nome").execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception as e:
            st.error(f"Errore caricamento Supabase: {e}")
    
    # Fallback: SQLite
    conn = sqlite3.connect("trico_database.db", timeout=30)
    df = pd.read_sql_query("SELECT * FROM prodotti ORDER BY categoria, nome", conn)
    conn.close()
    return df

# ============================================================================
# 🆕 QUI DEVI INSERIRE LA FUNZIONE MANCANTE PER GOOGLE DRIVE
# ============================================================================
def invia_file_a_google_drive(
    file_bytes, nome_file, nome_cliente, mime_type="application/pdf"
):
    """Invia file a Google Drive tramite webhook"""
    
    # 1. Legge il webhook da session_state o dal file
    webhook_url = st.session_state.get("gdrive_webhook_url", "") or os.getenv(
        "GDRIVE_WEBHOOK_URL", ""
    )

    if not webhook_url and os.path.exists("gdrive_webhook.txt"):
        try:
            with open("gdrive_webhook.txt", "r") as f:
                webhook_url = f.read().strip()
        except Exception:
            pass

    if not webhook_url:
        return False, "Webhook Google Drive non configurato. Inserisci l'URL nella sidebar."

    try:
        # 2. Codifica il file in base64
        b64_file = base64.b64encode(file_bytes).decode("utf-8")
        
        # 3. Prepara il payload per lo script Google Apps
        payload = {
            "clientFolder": str(nome_cliente).strip(),
            "fileName": str(nome_file).strip(),
            "fileBase64": b64_file,
            "mimeType": mime_type,
        }
        
        # 4. Invia la richiesta al webhook
        resp = requests.post(webhook_url.strip(), json=payload, timeout=30)
        
        # 5. Gestisce la risposta
        if resp.status_code == 200:
            try:
                res_json = resp.json()
                if res_json.get("status") == "success":
                    return True, f"✅ File salvato su Google Drive: {res_json.get('finalFileName', nome_file)}"
                else:
                    return False, f"❌ Errore Google Drive: {res_json.get('message', 'Errore sconosciuto')}"
            except:
                return True, "✅ File inviato a Google Drive (risposta non JSON)"
        else:
            return False, f"❌ Errore HTTP {resp.status_code}: {resp.text[:200]}"
            
    except requests.exceptions.Timeout:
        return False, "⏰ Timeout: Google Drive non risponde (30 secondi)"
    except requests.exceptions.ConnectionError:
        return False, "🔌 Errore di connessione a Google Drive"
    except Exception as e:
        return False, f"❌ Errore invio: {str(e)}"


# ============================================================================
# MAIN APPLICATION & INTERFACCIA STREAMLIT
# ============================================================================
def main():
    st.markdown(
        """
    <div style="background: linear-gradient(90deg, #1e3a5f, #2d5f8a); padding: 20px; border-radius: 10px; color: white; text-align: center; margin-bottom: 30px;">
        <h1>🔬 Studio Tricologico Righetti Since 1967</h1>
        <p>Sistema Avanzato di Analisi Tricologica Dermo-Cosmetica</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    conn = init_db()

    # ============================================================
    # SIDEBAR: GESTIONE CLIENTE CON AUTO-SYNC E CANCELLAZIONE
    # ============================================================
    with st.sidebar:
        st.header("👤 Gestione Cliente")

        # 1. Sincronizzazione Automatica Google Sheets (Salvata in memoria)
        config_file_sheet = "google_sheet_url.txt"
        link_salvato = ""
        if os.path.exists(config_file_sheet):
            with open(config_file_sheet, "r") as f:
                link_salvato = f.read().strip()

        webhook_saved = st.session_state.get("gdrive_webhook_url", "")
        if not webhook_saved and os.path.exists("gdrive_webhook.txt"):
            with open("gdrive_webhook.txt", "r") as f:
                webhook_saved = f.read().strip()

        # --- 1. EXPANDER COLLEGAMENTO GOOGLE ---
        with st.expander("🔄 Collegamento Google Sheets", expanded=False):
            link_foglio = st.text_input(
                "1. Link del Foglio Google:",
                value=link_salvato,
                placeholder="https://docs.google.com/spreadsheets/d/...",
                key="input_google_sheet_url",
            )

            link_webhook_input = st.text_input(
                "2. Webhook Google Drive:",
                value=webhook_saved,
                placeholder="https://script.google.com/macros/s/.../exec",
                key="input_gdrive_webhook",
            )

            if link_webhook_input.strip() and link_webhook_input != webhook_saved:
                with open("gdrive_webhook.txt", "w") as f_w:
                    f_w.write(link_webhook_input.strip())
                st.session_state["gdrive_webhook_url"] = link_webhook_input.strip()

            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button(
                    "💾 Salva Link", key="btn_save_url", use_container_width=True
                ):
                    with open(config_file_sheet, "w") as f:
                        f.write(link_foglio.strip())
                    st.success("Link salvato per l'auto-sync!")
                    st.rerun()
            with col_s2:
                if st.button(
                    "🔄 Sincronizza Ora",
                    key="btn_sync_manuale",
                    use_container_width=True,
                ):
                    if link_foglio.strip():
                        ok_s, msg_s = sincronizza_google_sheets(
                            link_foglio.strip(), conn
                        )
                        if ok_s:
                            st.success(msg_s)
                            st.rerun()
                        else:
                            st.error(msg_s)

        # Auto-Sync silenzioso all'avvio se il link è salvato
        if link_salvato and "auto_sync_eseguito" not in st.session_state:
            sincronizza_google_sheets(link_salvato, conn)
            st.session_state["auto_sync_eseguito"] = True

        # 2. Nuovo Cliente Manuale
        with st.expander("➕ Nuovo Cliente Manuale", expanded=False):
            nuovo_cliente = st.text_input(
                "Nome e Cognome", placeholder="Es. Mario Rossi"
            )
            nuovo_sesso = st.radio(
                "Profilo Fisiologico:",
                ["Uomo", "Donna"],
                horizontal=True,
                key="nuovo_sesso_radio",
            )
            if st.button(
                "➕ Registra Cliente",
                key="btn_reg_cliente",
                use_container_width=True,
            ):
                if nuovo_cliente.strip():
                    try:
                        c = conn.cursor()
                        c.execute(
                            "INSERT INTO clienti (codice_cliente, sesso) VALUES (?, ?)",
                            (nuovo_cliente.strip(), nuovo_sesso),
                        )
                        conn.commit()
                        st.success(f"Cliente '{nuovo_cliente}' registrato!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Cliente già esistente!")
                else:
                    st.warning("Inserisci il nome del cliente.")

        # 3. Elenco Clienti con Auto-Compilazione Completa
        df_clienti = pd.read_sql_query(
            "SELECT id, codice_cliente, sesso, cellulare, email FROM clienti ORDER BY codice_cliente",
            conn,
        )
        clienti_list = (
            df_clienti["codice_cliente"].tolist() if not df_clienti.empty else []
        )
        cliente_selezionato = st.selectbox(
            "Seleziona Cliente", ["-- Seleziona --"] + clienti_list
        )

        sesso_cliente = "Uomo"
        cell_default = ""
        email_default = ""

        if cliente_selezionato != "-- Seleziona --":
            riga_cl = df_clienti[
                df_clienti["codice_cliente"] == cliente_selezionato
            ].iloc[0]
            cl_id_selezionato = int(riga_cl["id"])
            sesso_cliente_db = (
                riga_cl["sesso"] if pd.notna(riga_cl["sesso"]) else "Uomo"
            )
            idx_sesso = 0 if sesso_cliente_db == "Uomo" else 1

            cell_default = (
                str(riga_cl["cellulare"]).replace("None", "").strip()
                if pd.notna(riga_cl.get("cellulare"))
                else ""
            )
            email_default = (
                str(riga_cl["email"]).replace("None", "").strip()
                if pd.notna(riga_cl.get("email"))
                else ""
            )

            sesso_cliente = st.radio(
                "Profilo Fisiologico Attivo:",
                ["Uomo", "Donna"],
                index=idx_sesso,
                horizontal=True,
                key=f"sesso_active_{cliente_selezionato}",
            )

            if sesso_cliente != sesso_cliente_db:
                c = conn.cursor()
                c.execute(
                    "UPDATE clienti SET sesso = ? WHERE codice_cliente = ?",
                    (sesso_cliente, cliente_selezionato),
                )
                conn.commit()

            # 4. Box Eliminazione Cliente Sicura
            with st.expander("🗑️ Elimina Cliente"):
                st.caption(
                    f"Eliminazione anagrafica e storico di: **{cliente_selezionato}**"
                )
                conferma_canc = st.checkbox(
                    "Confermo eliminazione definitiva",
                    key=f"chk_del_{cl_id_selezionato}",
                )
                if st.button(
                    "🗑️ Elimina Definitivamente",
                    key=f"btn_del_cl_{cl_id_selezionato}",
                    disabled=not conferma_canc,
                    use_container_width=True,
                ):
                    c = conn.cursor()
                    c.execute(
                        "DELETE FROM analisi WHERE cliente_id = ?",
                        (cl_id_selezionato,),
                    )
                    c.execute(
                        "DELETE FROM prodotti_cliente WHERE cliente_id = ?",
                        (cl_id_selezionato,),
                    )
                    c.execute("DELETE FROM clienti WHERE id = ?", (cl_id_selezionato,))
                    conn.commit()
                    st.success(f"Cliente '{cliente_selezionato}' eliminato!")
                    st.rerun()

        st.markdown("---")

        # 4. Configurazione AI Avanzata con MEMORIZZAZIONE CHIAVE PERMANENTE
        ai_key_file = "ai_api_key.txt"
        saved_ai_key = ""
        if os.path.exists(ai_key_file):
            with open(ai_key_file, "r") as f:
                saved_ai_key = f.read().strip()

        with st.expander("🤖 Configurazione AI Avanzata", expanded=False):
            ai_provider = st.selectbox(
                "Motore AI Perizia:",
                ["Groq (Istantaneo e Gratuito)", "OpenAI (GPT-4o)"],
            )

            if "Groq" in ai_provider:
                ai_api_key = st.text_input(
                    "Groq API Key:",
                    value=saved_ai_key,
                    type="password",
                    placeholder="gsk_...",
                    help="La chiave verrà memorizzata nel computer.",
                )

                col_k1, col_k2 = st.columns([1, 1])
                with col_k1:
                    if st.button(
                        "💾 Salva Chiave",
                        key="btn_save_ai_k",
                        use_container_width=True,
                    ):
                        with open(ai_key_file, "w") as f:
                            f.write(ai_api_key.strip())
                        st.success("✅ Chiave memorizzata!")
                        st.rerun()
                with col_k2:
                    if st.button(
                        "🗑️ Rimuovi",
                        key="btn_del_ai_k",
                        use_container_width=True,
                    ):
                        if os.path.exists(ai_key_file):
                            os.remove(ai_key_file)
                        st.success("Chiave rimossa!")
                        st.rerun()

                ai_modello_scelto = "qwen/qwen3.8-27b"
                if ai_api_key.strip():
                    try:
                        r_models = requests.get(
                            "https://api.groq.com/openai/v1/models",
                            headers={"Authorization": f"Bearer {ai_api_key.strip()}"},
                            timeout=4,
                        )
                        if r_models.status_code == 200:
                            lista_m = [m["id"] for m in r_models.json().get("data", [])]
                            lista_utili = [
                                m
                                for m in lista_m
                                if (
                                    "qwen" in m
                                    or "llama-3.3" in m
                                    or "llama-3.1" in m
                                    or "mixtral" in m
                                )
                                and "whisper" not in m
                                and "guard" not in m
                            ]
                            if not lista_utili:
                                lista_utili = lista_m
                            idx_def = 0
                            for target_m in [
                                "qwen/qwen3.8-27b",
                                "llama-3.3-70b-versatile",
                            ]:
                                if target_m in lista_utili:
                                    idx_def = lista_utili.index(target_m)
                                    break
                            ai_modello_scelto = st.selectbox(
                                "Modello Groq:", lista_utili, index=idx_def
                            )
                    except Exception:
                        pass
            else:
                ai_api_key = st.text_input(
                    "OpenAI API Key:",
                    value=saved_ai_key,
                    type="password",
                    placeholder="sk-proj-...",
                )
                if st.button(
                    "💾 Salva Chiave",
                    key="btn_save_oai_k",
                    use_container_width=True,
                ):
                    with open(ai_key_file, "w") as f:
                        f.write(ai_api_key.strip())
                    st.success("✅ Chiave memorizzata!")
                    st.rerun()
                ai_modello_scelto = "gpt-4o"

        st.markdown("---")

        # 5. Scala Alopecia Dinamica
        st.header("📐 Grado / Scala Alopecia")
        if sesso_cliente == "Uomo":
            scale_opzioni = [
                "Nessun diradamento evidente",
                "Scala Hamilton-Norwood: Grado I (Fisiologico)",
                "Scala Hamilton-Norwood: Grado II (Arretramento temporale lieve)",
                "Scala Hamilton-Norwood: Grado IIa (Arretramento frontale)",
                "Scala Hamilton-Norwood: Grado III (Arretramento profondo)",
                "Scala Hamilton-Norwood: Grado III Vertex (Diradamento al vertice)",
                "Scala Hamilton-Norwood: Grado IV (Vertice esteso + frontale)",
                "Scala Hamilton-Norwood: Grado IVa",
                "Scala Hamilton-Norwood: Grado V (Ponte residuo sottile)",
                "Scala Hamilton-Norwood: Grado Va",
                "Scala Hamilton-Norwood: Grado VI (Confluenza vertice-frontale)",
                "Scala Hamilton-Norwood: Grado VII (Corona ippocratica residua)",
            ]
            scala_selezionata = st.selectbox(
                "Stadio Hamilton-Norwood (Uomo):",
                scale_opzioni,
                key=f"scala_uomo_{cliente_selezionato}",
            )
        else:
            scale_opzioni = [
                "Nessun diradamento evidente",
                "Scala Ludwig: Grado I-1 (Diradamento iniziale lieve)",
                "Scala Ludwig: Grado I-2",
                "Scala Ludwig: Grado I-3 (Diradamento evidente riga centrale)",
                "Scala Ludwig: Grado II-1 (Diradamento moderato diffuso)",
                "Scala Ludwig: Grado II-2",
                "Scala Ludwig: Grado III (Diradamento severo con trasparenza)",
                "Scala Sinclair: Grado 1-2 (Pattern diffuso)",
                "Scala Sinclair: Grado 3-4 (Marcata rarefazione)",
                "Scala Sinclair: Grado 5 (Alopecia avanzata)",
            ]
            scala_selezionata = st.selectbox(
                "Stadio Ludwig / Sinclair (Donna):",
                scale_opzioni,
                key=f"scala_donna_{cliente_selezionato}",
            )

        st.markdown("---")

        # 6. Dati Check-up con NUMERO PROGRESSIVO AUTOMATICO DA 679
        st.header("📋 Dati Check-up")

        # Calcolo del numero progressivo a partire da 679
        c = conn.cursor()
        conteggio_analisi = c.execute("SELECT COUNT(*) FROM analisi").fetchone()[0]
        numero_checkup_automatico = 679 + int(conteggio_analisi or 0)

        checkup_num = st.number_input(
            "Check-up Nr.",
            min_value=1,
            value=numero_checkup_automatico,
            step=1,
            help="Numero progressivo del check-up (parte da 679 e aumenta da solo a ogni visita salvata).",
        )

        eta_cliente = st.number_input("Età", min_value=1, max_value=120, value=35)

        cell_cliente = st.text_input(
            "Cellulare",
            value=cell_default,
            key=f"cell_{cliente_selezionato}",
            placeholder="+39 333...",
        )
        email_cliente = st.text_input(
            "Email",
            value=email_default,
            key=f"email_{cliente_selezionato}",
            placeholder="email@esempio.it",
        )

        nota_operatore_extra = st.text_area(
            "Note Interne Studio (Opzionale):",
            key=f"note_interne_sidebar_{cliente_selezionato}",
            height=80,
            placeholder="Eventuali annotazioni o richieste del cliente...",
        )

        st.markdown("---")

        # 7. Sintomatologia & Anamnesi
        st.header("🩺 Sintomatologia & Anamnesi")
        chk_prurito = st.checkbox("🔴 Prurito / Bruciore")
        chk_dolore = st.checkbox("⚡ Tricodinia (Dolore al cuoio capelluto)")
        chk_caduta = st.checkbox("🍂 Caduta abbondante recente (Effluvio)")
        chk_sebo_iper = st.checkbox("💧 Ipersecrezione sebacea / Cute grassa")

        quadro_clinico = st.selectbox(
            "Orientamento Fito-Tricologico:",
            [
                "Standard / Riequilibrio Fisiologico",
                "Tendenza Androgenetica (AGA)",
                "Quadro Seborroico / Desquamazione Cerosa",
                "Desquamazione Secca / Pitiriasi",
                "Ipercheratosi Lamellare / Psoriasiforme",
                "Telogen Effluvio (Caduta reattiva / temporanea)",
            ],
            key="sel_quadro_clinico",
        )

        sintomi_dict = {
            "prurito": chk_prurito,
            "dolore": chk_dolore,
            "caduta_abbondante": chk_caduta,
            "sebo_eccesso": chk_sebo_iper,
            "quadro_ipotesi": quadro_clinico,
            "scala_alopecia": scala_selezionata,
            "sesso": sesso_cliente,
        }

    # ============================================================
    # TABS PRINCIPALI (5 TAB PERFETTAMENTE ALLINEATI)
    # ============================================================
    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "📸 Analisi & Report",
            "📦 Prodotti & Scheda Cura",
            "📊 Dashboard Grafici",
            "📈 Storico & Gestione Visite",
            "⚙️ Gestione Prodotti & Categorie",
        ]
    )

    # ============================================================
    # TAB 1: ANALISI CON CHECK-UP DI CONTROLLO & CONFRONTO EVOLUTIVO
    # ============================================================
    with tab1:
        if cliente_selezionato == "-- Seleziona --":
            st.info(
                "⚠️ Seleziona un cliente dalla barra laterale per avviare la seduta di analisi."
            )
        else:
            st.success(
                f"👤 Scheda Analisi Attiva: **{cliente_selezionato}** ({sesso_cliente}) — {scala_selezionata}"
            )

            def reset_testo_callback(chiave_da_aggiornare, nuovo_testo):
                st.session_state[chiave_da_aggiornare] = nuovo_testo

            # -------------------------------------------------------------
            # SEZIONE CONFRONTO PREGRESSO (DATABASE O PDF)
            # -------------------------------------------------------------
            with st.expander(
                "🔄 Check-up di Controllo: Confronto Evolutivo (Prima / Dopo)",
                expanded=False,
            ):
                modalita_confronto = st.radio(
                    "Modalità di Confronto:",
                    [
                        "❌ Nessun confronto (Prima Visita)",
                        "📊 Confronto Automatico da Storico Database",
                        "📄 Carica PDF Visita Precedente",
                    ],
                    horizontal=True,
                    key="radio_modalita_confronto",
                )

                dati_visita_precedente = None
                prodotti_visita_precedente = ""

                if modalita_confronto == "📊 Confronto Automatico da Storico Database":
                    c = conn.cursor()
                    cl_id_tmp = c.execute(
                        "SELECT id FROM clienti WHERE codice_cliente = ?",
                        (cliente_selezionato,),
                    ).fetchone()[0]
                    analisi_precedenti = pd.read_sql_query(
                        "SELECT * FROM analisi WHERE cliente_id = ? ORDER BY data DESC",
                        conn,
                        params=(cl_id_tmp,),
                    )

                    if not analisi_precedenti.empty:
                        # Date in formato italiano GG/MM/AAAA HH:MM
                        opzioni_visite = [
                            f"Check-up del {formatta_data_it(r['data'])} — (Calibro: {r['calibro_medio']} µm | Anisotropia: {r['anisotropia']}%)"
                            for _, r in analisi_precedenti.iterrows()
                        ]

                        visita_scelta_str = st.selectbox(
                            "Seleziona quale visita passata vuoi confrontare:",
                            opzioni_visite,
                            key=f"sel_visita_confronto_{cliente_selezionato}",
                            help="Puoi scegliere l'ultimo controllo oppure la primissima visita per vedere i progressi complessivi.",
                        )

                        idx_scelta = opzioni_visite.index(visita_scelta_str)
                        visita_scelta = analisi_precedenti.iloc[idx_scelta]

                        prod_prec = pd.read_sql_query(
                            """
                            SELECT p.nome FROM prodotti_cliente pc 
                            INNER JOIN prodotti p ON pc.prodotto_id = p.id 
                            WHERE pc.cliente_id = ?
                        """,
                            conn,
                            params=(cl_id_tmp,),
                        )
                        prodotti_visita_precedente = (
                            ", ".join(prod_prec["nome"].tolist())
                            if not prod_prec.empty
                            else ""
                        )

                        dati_visita_precedente = {
                            "data": visita_scelta["data"],
                            "calibro_medio": float(visita_scelta["calibro_medio"] or 0),
                            "anisotropia": float(visita_scelta["anisotropia"] or 0),
                            "densita_f": int(visita_scelta["densita_f"] or 0),
                            "eritemi": int(visita_scelta["eritemi"] or 0),
                            "tappi_sebacei": int(visita_scelta["osti_intasati"] or 0),
                            "steli_nuovi": int(visita_scelta["steli_nuovi"] or 0),
                            "checkup_num": f"ID #{visita_scelta['id']}",
                        }

                        st.info(
                            f"📌 **Confronto attivo con:** Check-up del **{dati_visita_precedente['data']}** | Calibro: **{dati_visita_precedente['calibro_medio']} µm** | Anisotropia: **{dati_visita_precedente['anisotropia']}%**"
                        )
                    else:
                        st.warning(
                            "Nessuna visita precedente registrata nel database per questo cliente."
                        )

                elif modalita_confronto == "📄 Carica PDF Visita Precedente":
                    uploaded_pdf = st.file_uploader(
                        "Carica il Report PDF del Check-up precedente",
                        type=["pdf"],
                        key="uploader_pdf_precedente",
                    )
                    if uploaded_pdf is not None:
                        pdf_bytes = uploaded_pdf.read()
                        dati_visita_precedente = estrai_dati_da_pdf_report(pdf_bytes)
                        st.success(
                            f"✅ PDF caricato! Data rilevata: **{dati_visita_precedente['data']}**"
                        )

            # -------------------------------------------------------------
            # FOTO PANORAMICA (UPLOAD FILE OPPURE SCATTO DAL VIVO CON IPHONE)
            # -------------------------------------------------------------
            with st.expander(
                "📱 Foto Panoramica Globale da PC | Smartphone",
                expanded=False,
            ):
                st.caption(
                    "Tocca 'Upload' e scegli 'Scatta foto' dal tuo Smartphone per fotografare la testa dall'alto ad altissima risoluzione."
                )
                uploaded_macro_phone = st.file_uploader(
                    "Carica o Scatta Foto da PC o Smartphone (JPG / PNG):",
                    type=["jpg", "jpeg", "png"],
                    key=f"macro_phone_file_{cliente_selezionato}",
                )

                if uploaded_macro_phone is not None:
                    col_ph1, col_ph2 = st.columns([1.2, 1])
                    with col_ph1:
                        st.image(
                            uploaded_macro_phone,
                            caption=f"Panoramica Globale — {cliente_selezionato}",
                            width=300,
                        )
                    with col_ph2:
                        st.write("")
                        st.write("")
                        if st.button(
                            "💾 Archivia Foto Panoramica",
                            key=f"btn_save_solo_macro_{cliente_selezionato}",
                            help="Salva la foto nella cartella del cliente sul Desktop",
                            use_container_width=True,
                        ):
                            cartella_cliente_dest = trova_o_crea_cartella_cliente(
                                cliente_selezionato
                            )
                            data_macro_str = datetime.now().strftime("%d-%m-%Y")
                            prefisso_macro = calcola_prefisso_da_file_esistenti(
                                cartella_cliente_dest, "Panoramica"
                            )
                            nome_file_macro = f"{prefisso_macro}Foto Panoramica | {data_macro_str}.jpg"
                            path_macro_dest = os.path.join(
                                cartella_cliente_dest, nome_file_macro
                            )

                            with open(path_macro_dest, "wb") as f_macro:
                                f_macro.write(uploaded_macro_phone.getbuffer())

                            st.success(
                                f"✅ Foto archiviata in: **PERCORSO CLIENTI/{os.path.basename(cartella_cliente_dest)}/{nome_file_macro}**"
                            )

            # -------------------------------------------------------------
            # CARICAMENTO IMMAGINI ODIERNE
            # -------------------------------------------------------------
            uploaded_files = st.file_uploader(
                "📤 Carica immagini tricoscopiche della seduta odierna",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True,
            )

            if uploaded_files:
                immagini_con_etichette = []

                for idx, uploaded_file in enumerate(uploaded_files):
                    st.markdown(f"---")
                    st.subheader(f"📷 Acquisizione #{idx+1} — {uploaded_file.name}")

                    file_bytes = np.asarray(
                        bytearray(uploaded_file.read()), dtype=np.uint8
                    )
                    img_raw = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
                    img_rgb = cv2.cvtColor(img_raw, cv2.COLOR_BGR2RGB)

                    col_opt1, col_opt2, col_opt3 = st.columns(3)
                    with col_opt1:
                        ottica = st.selectbox(
                            "Ottica / Ingrandimento",
                            ["50x", "200x"],
                            key=f"opt_ottica_{idx}",
                        )
                    with col_opt2:
                        luce = st.selectbox(
                            "Tipo di Luce",
                            ["Bianca", "Polarizzata"],
                            key=f"opt_luce_{idx}",
                        )
                    with col_opt3:
                        zona = st.selectbox(
                            "Area Cuoio Capelluto",
                            [
                                "Vertice (Chierica / Corona)",
                                "Frontale (Attaccatura / Ciuffo)",
                                "Tempie (Stempiature / Bitemporale)",
                                "Parietale / Mediana (Centro testa / Riga)",
                                "Occipitale (Nuca / Zona di confronto sana)",
                            ],
                            key=f"opt_zona_{idx}",
                        )

                    risultato = analizza_immagine_tricoscopica_pro(
                        img_rgb,
                        lente=ottica,
                        luce=luce,
                        zona=zona,
                        parametri_cliente=sintomi_dict,
                    )

                    note_key = f"note_area_{cliente_selezionato}_{idx}"
                    tracker_key = f"tracker_params_{cliente_selezionato}_{idx}"
                    config_attuale = f"{ottica}_{luce}_{zona}_{sesso_cliente}_{scala_selezionata}_{quadro_clinico}_{chk_prurito}_{chk_dolore}_{chk_caduta}_{chk_sebo_iper}_{modalita_confronto}"

                    if (
                        tracker_key not in st.session_state
                        or st.session_state[tracker_key] != config_attuale
                    ):
                        st.session_state[tracker_key] = config_attuale
                        st.session_state[note_key] = risultato["note_auto"]
                    elif note_key not in st.session_state:
                        st.session_state[note_key] = risultato["note_auto"]

                    col_img, col_dettagli = st.columns([1.2, 1])

                    with col_img:
                        st.image(
                            risultato["immagine_annotata"],
                            caption=f"Mappatura {zona} - {ottica} ({luce})",
                            use_container_width=True,
                        )

                        st.markdown(
                            """
                        <div style="background-color: #f8f9fa; padding: 10px; border-radius: 8px; border: 1px solid #e9ecef; font-size: 13px;">
                            <b>Legenda Marker:</b><br>
                            🟡 <b>Giallo:</b> Tappi sebacei / Ipercheratosi &nbsp;|&nbsp; 
                            🔴 <b>Rosso:</b> Iperemia / Alone perifollicolare<br>
                            🟣 <b>Viola:</b> Germogli anagen ricrescita<br>
                            🟢 <b>Verde:</b> Ostio sano con stelo
                        </div>
                        """,
                            unsafe_allow_html=True,
                        )

                    with col_dettagli:
                        # Stile CSS per non troncare i testi con i puntini (...)
                        st.markdown(
                            """
                        <style>
                        div[data-testid="stMetricValue"] > div {
                            font-size: 1.35rem !important;
                            font-weight: 700 !important;
                            white-space: normal !important;
                            line-height: 1.2 !important;
                        }
                        div[data-testid="stMetricLabel"] > div {
                            font-size: 0.82rem !important;
                            font-weight: 500 !important;
                        }
                        </style>
                        """,
                            unsafe_allow_html=True,
                        )

                        st.markdown(f"##### 🔬 Parametri Rilevati: Area {zona}")

                        # Prima riga di metriche: Biometria Principale
                        m1, m2, m3 = st.columns(3)
                        valore_densita = (
                            f"{risultato['densita_stimata']} cap/cm²"
                            if ottica == "50x"
                            else f"{len(risultato['spessori_um'])} steli (200x)"
                        )
                        m1.metric("Densità", valore_densita)
                        m2.metric("Calibro Medio", f"{risultato['calibro_medio']} µm")
                        m3.metric("Anisotropia", f"{risultato['anisotropia']} %")

                        # Seconda riga di metriche: Anomalie & Attività Follicolare
                        m4, m5, m6 = st.columns(3)
                        m4.metric("🟡 Tappi Sebacei", risultato["tappi_sebacei"])
                        m5.metric(
                            "🔵 Follicoli Silenti",
                            risultato["follicoli_dormienti"],
                        )
                        m6.metric("🟣 Germogli Anagen", risultato["steli_nuovi"])

                        st.markdown("##### 📝 Sintesi Immagine (Soli Punti Chiave)")
                        nota_operatore_img = st.text_area(
                            "Descrizione sintetica immagine:",
                            key=note_key,
                            height=100,
                        )

                        st.button(
                            "🔄 Ricalcola Testo AI",
                            key=f"btn_reset_note_{idx}",
                            on_click=reset_testo_callback,
                            args=(note_key, risultato["note_auto"]),
                            help="Ripristina il testo automatico dell'AI per questa foto",
                            use_container_width=True,
                        )

                    immagini_con_etichette.append(
                        {
                            "immagine": risultato["immagine_annotata"],
                            "ottica": ottica,
                            "luce": luce,
                            "zona": zona,
                            "note": nota_operatore_img,
                            "steli_anagen": risultato["steli_anagen"],
                            "steli_vellus": risultato["steli_vellus"],
                            "steli_nuovi": risultato["steli_nuovi"],
                            "eritemi": risultato["eritema_diffuso"],
                            "tappi_sebacei": risultato["tappi_sebacei"],
                            "calibro_medio": risultato["calibro_medio"],
                            "anisotropia": risultato["anisotropia"],
                            "densita": risultato["densita_stimata"],
                        }
                    )

                # -------------------------------------------------------------
                # CALCOLO MEDIE GLOBALI PONDERATE
                # -------------------------------------------------------------
                foto_200x = [
                    r
                    for r in immagini_con_etichette
                    if r["ottica"] == "200x" and r["calibro_medio"] > 0
                ]
                if foto_200x:
                    media_cal_oggi = round(
                        float(np.mean([r["calibro_medio"] for r in foto_200x])),
                        1,
                    )
                    media_ani_oggi = round(
                        float(np.mean([r["anisotropia"] for r in foto_200x])), 1
                    )
                else:
                    cal_val = [
                        r["calibro_medio"]
                        for r in immagini_con_etichette
                        if r["calibro_medio"] > 0
                    ]
                    media_cal_oggi = (
                        round(float(np.mean(cal_val)), 1) if cal_val else 0.0
                    )
                    ani_val = [
                        r["anisotropia"]
                        for r in immagini_con_etichette
                        if r["anisotropia"] > 0
                    ]
                    media_ani_oggi = (
                        round(float(np.mean(ani_val)), 1) if ani_val else 0.0
                    )

                den_val = [
                    r["densita"] for r in immagini_con_etichette if r["densita"] > 0
                ]
                media_den_oggi = int(round(np.mean(den_val))) if den_val else 0

                tot_tappi_oggi = sum(r["tappi_sebacei"] for r in immagini_con_etichette)
                tot_eritemi_oggi = sum(r["eritemi"] for r in immagini_con_etichette)
                tot_nuovi_oggi = sum(r["steli_nuovi"] for r in immagini_con_etichette)

                dati_sessione_globale = {
                    "calibro_medio": media_cal_oggi,
                    "anisotropia": media_ani_oggi,
                    "densita_f": media_den_oggi,
                    "tappi_sebacei": tot_tappi_oggi,
                    "eritemi": tot_eritemi_oggi,
                    "steli_nuovi": tot_nuovi_oggi,
                }

                # -------------------------------------------------------------
                # BOX CONFRONTO EVOLUTIVO AI (SE ATTIVO)
                # -------------------------------------------------------------
                comparativa = None
                if dati_visita_precedente and immagini_con_etichette:
                    st.markdown("---")
                    st.subheader("📈 Risultati del Confronto Evolutivo (Prima / Oggi)")

                    comparativa = genera_valutazione_comparativa_ai(
                        dati_visita_precedente,
                        dati_sessione_globale,
                        sesso_cliente,
                        scala_selezionata,
                        prodotti_visita_precedente,
                    )

                    cal_p_val = dati_visita_precedente.get("calibro_medio", 0.0)
                    ani_p_val = dati_visita_precedente.get("anisotropia", 0.0)
                    den_p_val = dati_visita_precedente.get("densita_f", 0)

                    d_den = media_den_oggi - den_p_val
                    p_den = (
                        round((d_den / den_p_val) * 100, 1) if den_p_val > 0 else 0.0
                    )
                    perc_cal = (
                        round((comparativa["delta_cal"] / cal_p_val) * 100, 1)
                        if cal_p_val > 0
                        else 0.0
                    )
                    perc_ani = (
                        round((comparativa["delta_ani"] / ani_p_val) * 100, 1)
                        if ani_p_val > 0
                        else 0.0
                    )

                    tempo_trascorso = "Periodo di controllo"
                    try:
                        d_prec = None
                        raw_date = str(dati_visita_precedente.get("data", "")).strip()
                        for fmt in (
                            "%Y-%m-%d %H:%M",
                            "%d/%m/%Y",
                            "%Y-%m-%d",
                            "%d-%m-%Y",
                        ):
                            try:
                                d_prec = datetime.strptime(
                                    raw_date.split()[0], fmt.split()[0]
                                )
                                break
                            except Exception:
                                pass
                        if d_prec:
                            days_diff = (datetime.now() - d_prec).days
                            if days_diff > 30:
                                tempo_trascorso = f"{days_diff} giorni (~{round(days_diff/30, 1)} mesi)"
                            else:
                                tempo_trascorso = f"{days_diff} giorni"
                    except Exception:
                        pass

                    st.session_state[f"dati_confronto_pdf_{cliente_selezionato}"] = {
                        "data_prec": dati_visita_precedente.get("data", "Precedente"),
                        "cal_p": cal_p_val,
                        "cal_a": media_cal_oggi,
                        "delta_cal": comparativa["delta_cal"],
                        "perc_cal": perc_cal,
                        "ani_p": ani_p_val,
                        "ani_a": media_ani_oggi,
                        "delta_ani": comparativa["delta_ani"],
                        "perc_ani": perc_ani,
                        "den_p": den_p_val,
                        "den_a": media_den_oggi,
                        "delta_den": d_den,
                        "perc_den": p_den,
                        "tap_p": dati_visita_precedente.get("tappi_sebacei", 0),
                        "tap_a": tot_tappi_oggi,
                        "delta_tap": comparativa["delta_tap"],
                        "prodotti_prec": prodotti_visita_precedente,
                        "tempo_trascorso": tempo_trascorso,
                        "sintesi_ai": comparativa["testo"]
                        .replace("📊 RELAZIONE COMPARATIVA DI CONTROLLO:", "")
                        .strip(),
                    }

                    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
                    col_c1.metric(
                        "Variazione Densità",
                        f"{media_den_oggi} cap/cm²",
                        delta=f"{'+' if d_den > 0 else ''}{d_den} cap/cm² ({'+' if p_den > 0 else ''}{p_den}%)",
                    )
                    col_c2.metric(
                        "Variazione Calibro",
                        f"{media_cal_oggi} µm",
                        delta=f"{comparativa['delta_cal']} µm ({'+' if perc_cal > 0 else ''}{perc_cal}%)",
                    )
                    col_c3.metric(
                        "Variazione Anisotropia",
                        f"{media_ani_oggi} %",
                        delta=f"{comparativa['delta_ani']} %",
                        delta_color="inverse",
                    )
                    col_c4.metric(
                        "Tappi Sebacei",
                        f"{tot_tappi_oggi}",
                        delta=f"{comparativa['delta_tap']}",
                        delta_color="inverse",
                    )

                    st.info(comparativa["testo"])

                # -------------------------------------------------------------
                # RELAZIONE GLOBALE AI (6-8 RIGHE CON FOCUS TRATTAMENTO)
                # -------------------------------------------------------------
                st.markdown("---")
                st.subheader("📋 Relazione Globale Check-up (Sintesi per Report PDF)")
                st.caption(
                    "Questa sintesi di 6-8 righe riassume tutte le foto e definisce il focus del trattamento che verrà stampato a pagina 2 del Report PDF."
                )

                confronto_per_sintesi = st.session_state.get(
                    f"dati_confronto_pdf_{cliente_selezionato}", None
                )

                if ai_api_key.strip():
                    img_sample_bgr = cv2.cvtColor(
                        immagini_con_etichette[0]["immagine"], cv2.COLOR_RGB2BGR
                    )
                    sintesi_globale_calcolata = esegui_perizia_vision_ai(
                        img_sample_bgr,
                        ai_api_key,
                        ai_provider,
                        ai_modello_scelto,
                        {
                            "calibro": media_cal_oggi,
                            "anisotropia": media_ani_oggi,
                            "densita": media_den_oggi,
                            "tappi": tot_tappi_oggi,
                            "eritemi": tot_eritemi_oggi,
                        },
                        sesso_cliente,
                        scala_selezionata,
                        "Multi-zona",
                        "Mista",
                        "Mista",
                        [k for k, v in sintomi_dict.items() if v is True],
                    )
                else:
                    sintesi_globale_calcolata = genera_sintesi_globale_operatore(
                        dati_sessione_globale,
                        sintomi_dict,
                        dati_confronto=confronto_per_sintesi,
                    )

                note_glob_key = f"note_operatore_gen_{cliente_selezionato}"
                tracker_glob_key = f"tracker_glob_{cliente_selezionato}"
                config_glob_tracker = f"{config_attuale}_{len(immagini_con_etichette)}_{media_cal_oggi}_{ai_api_key.strip()}"

                if (
                    tracker_glob_key not in st.session_state
                    or st.session_state[tracker_glob_key] != config_glob_tracker
                ):
                    st.session_state[tracker_glob_key] = config_glob_tracker
                    st.session_state[note_glob_key] = sintesi_globale_calcolata
                elif note_glob_key not in st.session_state:
                    st.session_state[note_glob_key] = sintesi_globale_calcolata

                col_not1, col_not2 = st.columns([4, 1])
                with col_not1:
                    nota_globale_finale = st.text_area(
                        "Relazione Globale (modificabile):",
                        key=note_glob_key,
                        height=160,
                    )
                with col_not2:
                    st.write("")
                    st.write("")
                    st.button(
                        "🔄 Rigenera Sintesi",
                        key=f"btn_regen_glob_{cliente_selezionato}",
                        on_click=reset_testo_callback,
                        args=(note_glob_key, sintesi_globale_calcolata),
                        help="Ricalcola la sintesi basandosi su tutte le foto e parametri caricati",
                        use_container_width=True,
                    )

                # -------------------------------------------------------------
                # SALVA SESSIONE (DATABASE + CARTELLA CLIENTE SU DESKTOP)
                # -------------------------------------------------------------
                st.markdown("---")
                col_b1, col_b2 = st.columns(2)

                with col_b1:
                    if st.button(
                        "💾 Salva Sessione di Analisi",
                        key="btn_salva_analisi_completa",
                        use_container_width=True,
                    ):
                        try:
                            c = conn.cursor()
                            cl_id = c.execute(
                                "SELECT id FROM clienti WHERE codice_cliente = ?",
                                (cliente_selezionato,),
                            ).fetchone()[0]
                            data_oggi = datetime.now().strftime("%d/%m/%Y %H:%M")
                            data_cartella_foto = datetime.now().strftime("%d-%m-%Y")

                            # Calcolo parametri
                            tot_steli = sum(
                                r["steli_anagen"] + r["steli_vellus"] + r["steli_nuovi"]
                                for r in immagini_con_etichette
                            )
                            tot_anagen = sum(
                                r["steli_anagen"] for r in immagini_con_etichette
                            )
                            tot_vellus = sum(
                                r["steli_vellus"] for r in immagini_con_etichette
                            )
                            tot_nuovi = sum(
                                r["steli_nuovi"] for r in immagini_con_etichette
                            )

                            # 1. SALVATAGGIO NEL DATABASE
                            c.execute(
                                """INSERT INTO analisi 
                                (cliente_id, data, zona, ingrandimento, luce, foto_caricate, steli_totale, steli_anagen, steli_vellus, steli_nuovi, calibro_medio, densita_f, anisotropia, perc_vellus, eritemi, dermatite_seborroica, forfora_secca, osti_intasati, prurito, routine_consigliata)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (
                                    cl_id,
                                    data_oggi,
                                    "Multi-zona",
                                    "50x/200x",
                                    "Mista",
                                    len(immagini_con_etichette),
                                    tot_steli,
                                    tot_anagen,
                                    tot_vellus,
                                    tot_nuovi,
                                    media_cal_oggi,
                                    media_den_oggi,
                                    media_ani_oggi,
                                    (
                                        round((tot_vellus / tot_steli) * 100, 1)
                                        if tot_steli > 0
                                        else 0
                                    ),
                                    tot_eritemi_oggi,
                                    0,
                                    0,
                                    tot_tappi_oggi,
                                    "Sì" if chk_prurito else "No",
                                    f"Scala: {scala_selezionata} | Quadro: {quadro_clinico}",
                                ),
                            )
                            conn.commit()

                            # 2. CARTELLA CLIENTE IN PERCORSO CLIENTI SUL DESKTOP
                            cartella_cliente_dest = trova_o_crea_cartella_cliente(
                                cliente_selezionato
                            )

                            # A. Salvataggio Cartella Foto Microcamera (con pallini)
                            nome_cartella_foto = f"Foto Check-Up | {data_cartella_foto}"
                            cartella_foto_checkup = os.path.join(
                                cartella_cliente_dest, nome_cartella_foto
                            )
                            os.makedirs(cartella_foto_checkup, exist_ok=True)

                            for i_f, f_data in enumerate(immagini_con_etichette, 1):
                                f_filename = f"Acquisizione_{i_f}_{f_data['zona'].split()[0]}_{f_data['ottica']}.png"
                                cv2.imwrite(
                                    os.path.join(cartella_foto_checkup, f_filename),
                                    cv2.cvtColor(f_data["immagine"], cv2.COLOR_RGB2BGR),
                                )

                            # B. Salvataggio Foto Panoramica Smartphone (se caricata)
                            msg_macro_info = ""
                            if (
                                "uploaded_macro_phone" in locals()
                                and uploaded_macro_phone is not None
                            ):
                                prefisso_macro = calcola_prefisso_da_file_esistenti(
                                    cartella_cliente_dest, "Panoramica"
                                )
                                nome_file_macro = f"{prefisso_macro}Foto Panoramica | {data_cartella_foto}.jpg"
                                path_macro_dest = os.path.join(
                                    cartella_cliente_dest, nome_file_macro
                                )
                                with open(path_macro_dest, "wb") as f_macro:
                                    f_macro.write(uploaded_macro_phone.getbuffer())
                                msg_macro_info = (
                                    f" + Foto Panoramica '{nome_file_macro}'"
                                )

                            st.success(
                                f"✅ Dati salvati e file archiviati in: **PERCORSO CLIENTI/{os.path.basename(cartella_cliente_dest)}/** ({nome_cartella_foto}{msg_macro_info})"
                            )
                        except Exception as e:
                            st.error(f"Errore durante il salvataggio: {e}")

                with col_b2:
                    if st.button(
                        "📄 Genera Report TricoCamera PDF",
                        key="btn_gen_pdf_pro",
                        use_container_width=True,
                    ):
                        success = False
                        cartella_cliente_dest = trova_o_crea_cartella_cliente(
                            cliente_selezionato
                        )

                        # Riconoscimento automatico del prefisso dai file già presenti nella cartella
                        prefisso_report = calcola_prefisso_da_file_esistenti(
                            cartella_cliente_dest, "Report"
                        )
                        pdf_filename = f"{cliente_selezionato} | {prefisso_report}Report Tricologico.pdf"
                        pdf_path = os.path.join(cartella_cliente_dest, pdf_filename)

                        nota_da_stampare = st.session_state.get(note_glob_key, "")
                        if not nota_da_stampare and "nota_globale_finale" in locals():
                            nota_da_stampare = nota_globale_finale

                        note_extra_str = (
                            str(nota_operatore_extra).strip()
                            if (
                                "nota_operatore_extra" in locals()
                                and nota_operatore_extra
                            )
                            else ""
                        )
                        if note_extra_str:
                            nota_da_stampare += f"\n\nNote Aggiuntive: {note_extra_str}"

                        template_path = "Report TricoCamera.pdf"
                        if not os.path.exists(template_path):
                            st.error(
                                f"⚠️ Il file modello '{template_path}' non è presente nella cartella del programma!"
                            )
                        else:
                            try:
                                success = genera_pdf_righetti_completo(
                                    nome_cliente=cliente_selezionato,
                                    eta=eta_cliente,
                                    cellulare=cell_cliente,
                                    email=email_cliente,
                                    nota_operatore=nota_da_stampare,
                                    checkup_num=checkup_num,
                                    num_immagini=len(immagini_con_etichette),
                                    immagini_con_etichette=immagini_con_etichette,
                                    path_salvataggio=pdf_path,
                                    template_path=template_path,
                                )
                            except Exception as e:
                                st.error(f"❌ Errore durante la creazione del PDF: {e}")
                                success = False

                        if success and os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as pdf_file:
                                st.download_button(
                                    "📥 Scarica Report PDF",
                                    pdf_file,
                                    pdf_filename,
                                    "application/pdf",
                                    use_container_width=True,
                                )
                            st.success(
                                f"✅ Report PDF archiviato in: **PERCORSO CLIENTI/{os.path.basename(cartella_cliente_dest)}/{pdf_filename}**"
                            )

    # ============================================================
    # TAB 2: PRODOTTI, PROTOCOLLO SEQUENZIALE & CURA DOMICILIARE
    # ============================================================
    with tab2:
        st.header("📦 Prodotti & Cura Domiciliare")
        if cliente_selezionato == "-- Seleziona --":
            st.info("⚠️ Seleziona un cliente dalla barra laterale")
        else:
            c = conn.cursor()
            res_cl = c.execute(
                "SELECT id FROM clienti WHERE codice_cliente = ?",
                (cliente_selezionato,),
            ).fetchone()

            if not res_cl:
                st.error("Cliente non trovato.")
            else:
                cl_id = int(res_cl[0])

                prodotti_assegnati = pd.read_sql_query(
                    """
                    SELECT pc.id AS assegnazione_id, pc.prodotto_id,
                           COALESCE(pc.modalita, p.modalita) AS modalita,
                           COALESCE(pc.frequenza, p.frequenza) AS frequenza,
                           COALESCE(pc.orario, p.orario) AS orario,
                           COALESCE(pc.dosi, p.dosi) AS dosi,
                           COALESCE(pc.tempi_posa, p.tempi_posa) AS tempi_posa,
                           COALESCE(pc.durata_utilizzo, p.durata_utilizzo) AS durata_utilizzo,
                           COALESCE(pc.note_utilizzo, p.note) AS note_utilizzo,
                           p.nome, p.categoria,
                           p.modalita AS modalita_default,
                           p.frequenza AS frequenza_default,
                           p.orario AS orario_default
                    FROM prodotti_cliente pc
                    INNER JOIN prodotti p ON pc.prodotto_id = p.id
                    WHERE pc.cliente_id = ?
                    ORDER BY pc.data_assegnazione DESC
                    """,
                    conn,
                    params=(cl_id,),
                )

                # ---------------------------------------------------------
                # SEZIONE 1: ASSEGNAZIONE PRODOTTI (CON TASTO SVUOTA LISTA)
                # ---------------------------------------------------------
                st.subheader("➕ Assegna Prodotti al Cliente")

                col_as_ai, col_as_clear = st.columns([3, 1])

                with col_as_ai:
                    if st.button(
                        "✨ Auto-Assegna Trattamento con AI (Matching Telecamera & INCI)",
                        key="btn_auto_ai_prescribe",
                        help="Azzera la vecchia lista e assegna la nuova cura personalizzata per oggi",
                        use_container_width=True,
                    ):
                        n_ass = auto_assegna_trattamento_righetti(
                            cl_id, conn, sintomi_dict
                        )

                        prod_aggiornati = pd.read_sql_query(
                            """
                            SELECT pc.*, p.nome, p.categoria 
                            FROM prodotti_cliente pc 
                            INNER JOIN prodotti p ON pc.prodotto_id = p.id 
                            WHERE pc.cliente_id = ?
                        """,
                            conn,
                            params=(cl_id,),
                        ).to_dict("records")

                        proto_key = f"proto_testo_{cliente_selezionato}"
                        st.session_state[proto_key] = (
                            genera_bozza_protocollo_automatico(prod_aggiornati)
                        )
                        st.success(
                            f"✅ Nuova cura Righetti assegnata ({n_ass} prodotti caricati da zero)!"
                        )
                        st.rerun()

                with col_as_clear:
                    if st.button(
                        "🧹 Svuota Elenco",
                        key="btn_clear_all_prod",
                        help="Cancella tutti i prodotti assegnati per ripartire da zero",
                        use_container_width=True,
                    ):
                        c.execute(
                            "DELETE FROM prodotti_cliente WHERE cliente_id = ?",
                            (cl_id,),
                        )
                        conn.commit()
                        proto_key = f"proto_testo_{cliente_selezionato}"
                        st.session_state[proto_key] = ""
                        st.success("Elenco prodotti svuotato!")
                        st.rerun()

                st.markdown("---")

                # Assegnazione manuale singolo prodotto
                df_tutti = pd.read_sql_query(
                    "SELECT * FROM prodotti ORDER BY nome", conn
                )
                if not prodotti_assegnati.empty:
                    ids_assegnati = prodotti_assegnati["prodotto_id"].tolist()
                    df_disponibili = df_tutti[~df_tutti["id"].isin(ids_assegnati)]
                else:
                    df_disponibili = df_tutti

                if not df_disponibili.empty:
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        sel = st.selectbox(
                            "Oppure aggiungi un singolo prodotto a mano:",
                            df_disponibili["nome"].tolist(),
                            key="sel_prodotto",
                        )
                    with col2:
                        st.write("")
                        if st.button(
                            "➕ Aggiungi Singolo",
                            key="btn_assegna",
                            use_container_width=True,
                        ):
                            try:
                                prod_row = df_disponibili[
                                    df_disponibili["nome"] == sel
                                ].iloc[0]
                                prod_id = int(prod_row["id"])
                                c.execute(
                                    """
                                    INSERT INTO prodotti_cliente 
                                    (cliente_id, prodotto_id, modalita, frequenza, orario, dosi, tempi_posa, durata_utilizzo, note_utilizzo) 
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                    (
                                        cl_id,
                                        prod_id,
                                        str(prod_row["modalita"] or ""),
                                        str(prod_row["frequenza"] or ""),
                                        str(prod_row["orario"] or ""),
                                        str(prod_row["dosi"] or ""),
                                        str(prod_row["tempi_posa"] or ""),
                                        str(prod_row["durata_utilizzo"] or ""),
                                        str(prod_row["note"] or ""),
                                    ),
                                )
                                conn.commit()
                                st.success(f"✅ Prodotto '{sel}' assegnato!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Errore durante l'assegnazione: {str(e)}")
                else:
                    st.info("✅ Tutti i prodotti sono già stati assegnati.")

                st.markdown("---")

                # 2. Protocollo Sequenziale
                st.subheader(
                    "📝 Protocollo di Utilizzo Sequenziale (Prima dei Prodotti nel PDF)"
                )
                st.caption(
                    "Scrivi qui la sequenza logica di applicazione per il cliente (es. alternanza shampoo, spray a cute tamponata, trattamenti periodici, durata primi mesi)."
                )

                proto_key = f"proto_testo_{cliente_selezionato}"
                prodotti_list_dict = (
                    prodotti_assegnati.to_dict("records")
                    if not prodotti_assegnati.empty
                    else []
                )

                def bozza_proto_callback():
                    st.session_state[proto_key] = genera_bozza_protocollo_automatico(
                        prodotti_list_dict
                    )

                if proto_key not in st.session_state:
                    st.session_state[proto_key] = genera_bozza_protocollo_automatico(
                        prodotti_list_dict
                    )

                col_pr1, col_pr2 = st.columns([4, 1])
                with col_pr1:
                    testo_protocollo_inserito = st.text_area(
                        "Istruzioni Sequenziali di Utilizzo (modificabili):",
                        key=proto_key,
                        height=160,
                    )
                with col_pr2:
                    st.write("")
                    st.write("")
                    st.button(
                        "✨ Bozza Automatica AI",
                        key=f"btn_bozza_proto_{cliente_selezionato}",
                        on_click=bozza_proto_callback,
                        help="Genera una sequenza ordinata in fasi basandosi sui prodotti attualmente assegnati",
                        use_container_width=True,
                    )

                st.markdown("---")

                # 3. Dettaglio Prodotti
                st.subheader("📋 Dettaglio Prodotti Assegnati")
                if not prodotti_assegnati.empty:
                    for _, prod in prodotti_assegnati.iterrows():
                        ass_id = int(prod["assegnazione_id"])
                        with st.expander(f"💊 {prod['nome']} — [{prod['categoria']}]"):
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                mod_modalita = st.text_input(
                                    "Modalità d'uso",
                                    value=prod["modalita"] or "",
                                    key=f"mod_{ass_id}",
                                )
                                mod_frequenza = st.text_input(
                                    "Frequenza",
                                    value=prod["frequenza"] or "",
                                    key=f"freq_{ass_id}",
                                )
                            with col2:
                                mod_orario = st.text_input(
                                    "Orario",
                                    value=prod["orario"] or "",
                                    key=f"ora_{ass_id}",
                                )
                                mod_dosi = st.text_input(
                                    "Dosi",
                                    value=prod["dosi"] or "",
                                    key=f"dosi_{ass_id}",
                                )
                            with col3:
                                mod_tempi = st.text_input(
                                    "Tempo di posa",
                                    value=prod["tempi_posa"] or "",
                                    key=f"tempi_{ass_id}",
                                )
                                mod_durata = st.text_input(
                                    "Durata trattamento",
                                    value=prod["durata_utilizzo"] or "",
                                    key=f"durata_{ass_id}",
                                )

                            mod_note = st.text_area(
                                "Note personalizzate per il cliente",
                                value=prod["note_utilizzo"] or "",
                                key=f"note_{ass_id}",
                            )

                            col_s1, col_s2 = st.columns(2)
                            with col_s1:
                                if st.button(
                                    "💾 Salva Modifiche",
                                    key=f"save_{ass_id}",
                                    use_container_width=True,
                                ):
                                    try:
                                        c.execute(
                                            """
                                            UPDATE prodotti_cliente 
                                            SET modalita=?, frequenza=?, orario=?, dosi=?, tempi_posa=?, durata_utilizzo=?, note_utilizzo=? 
                                            WHERE id=?
                                        """,
                                            (
                                                mod_modalita,
                                                mod_frequenza,
                                                mod_orario,
                                                mod_dosi,
                                                mod_tempi,
                                                mod_durata,
                                                mod_note,
                                                ass_id,
                                            ),
                                        )
                                        conn.commit()
                                        st.success("✅ Modifiche salvate!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(
                                            f"Errore durante il salvataggio: {str(e)}"
                                        )

                            with col_s2:
                                if st.button(
                                    "🗑️ Rimuovi dal Cliente",
                                    key=f"del_{ass_id}",
                                    use_container_width=True,
                                ):
                                    try:
                                        c.execute(
                                            "DELETE FROM prodotti_cliente WHERE id=?",
                                            (ass_id,),
                                        )
                                        conn.commit()
                                        st.success("✅ Rimosso!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(
                                            f"Errore durante l'eliminazione: {str(e)}"
                                        )
                else:
                    st.info("📭 Nessun prodotto assegnato a questo cliente.")

                # ---------------------------------------------------------
                # SEZIONE 4: GENERA SCHEDA CURA PDF (CON NOME FORMATTATO)
                # ---------------------------------------------------------
                st.markdown("---")
                # Nel TAB 2:
                if st.button(
                    "📄 Genera Scheda Cura PDF",
                    key="btn_scheda_cura",
                    use_container_width=True,
                ):
                    if not prodotti_assegnati.empty:
                        prodotti_list = prodotti_assegnati.to_dict("records")
                        cartella_cliente_dest = trova_o_crea_cartella_cliente(
                            cliente_selezionato
                        )

                        # Riconoscimento automatico del prefisso per il Rituale di Cura
                        prefisso_cura = calcola_prefisso_da_file_esistenti(
                            cartella_cliente_dest, "Rituale"
                        )
                        pdf_filename = f"{cliente_selezionato} | {prefisso_cura}Rituale di Cura Domiciliare.pdf"
                        pdf_path = os.path.join(cartella_cliente_dest, pdf_filename)

                        confronto_dati = st.session_state.get(
                            f"dati_confronto_pdf_{cliente_selezionato}", None
                        )
                        proto_da_stampare = st.session_state.get(
                            proto_key, testo_protocollo_inserito
                        )

                        success = genera_pdf_cura_domiciliare(
                            cliente_selezionato,
                            prodotti_list,
                            pdf_path,
                            dati_confronto=confronto_dati,
                            protocollo_testo=proto_da_stampare,
                        )
                        if success and os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as pdf_file:
                                st.download_button(
                                    "📥 Scarica Scheda Cura PDF",
                                    pdf_file,
                                    pdf_filename,
                                    "application/pdf",
                                    use_container_width=True,
                                )
                            st.success(
                                f"✅ Scheda Cura archiviata in: **PERCORSO CLIENTI/{os.path.basename(cartella_cliente_dest)}/{pdf_filename}**"
                            )
                    else:
                        st.warning("⚠️ Assegna almeno un prodotto al cliente.")

    # ============================================================
    # TAB 3: DASHBOARD GRAFICI & ANALYTICS EVOLUTIVE
    # ============================================================
    with tab3:
        st.header("📊 Dashboard & Monitoraggio Grafico Risultati")

        if cliente_selezionato == "-- Seleziona --":
            st.info(
                "⚠️ Seleziona un cliente dalla barra laterale per visualizzare i grafici."
            )
        else:
            c = conn.cursor()
            cl_id = c.execute(
                "SELECT id FROM clienti WHERE codice_cliente = ?",
                (cliente_selezionato,),
            ).fetchone()[0]

            # Recupera lo storico cronologico (dal più vecchio al più recente per i grafici)
            df_trend = pd.read_sql_query(
                """
                SELECT id, data, calibro_medio, densita_f, anisotropia, 
                       perc_vellus, eritemi, osti_intasati, steli_nuovi, steli_totale
                FROM analisi 
                WHERE cliente_id = ? 
                ORDER BY id ASC
                """,
                conn,
                params=(cl_id,),
            )

            if df_trend.empty:
                st.info(
                    f"📭 Nessun dato storico ancora registrato per **{cliente_selezionato}**."
                )
            else:
                # 1. Definizione sicura dell'ultima visita
                ultima_visita = df_trend.iloc[-1]
                data_ultima_it = formatta_data_it(ultima_visita["data"], con_ora=False)

                # Formattazione date in italiano per l'asse X dei grafici
                df_trend["Data_Visita"] = df_trend["data"].apply(
                    lambda d: formatta_data_it(d, con_ora=False)
                )

                # Pulsante di salvataggio PDF in alto a destra
                col_d_head1, col_d_head2 = st.columns([3, 1])
                with col_d_head1:
                    st.subheader(
                        f"🔬 Stato Biometrico Attuale (Check-up del {data_ultima_it})"
                    )
                with col_d_head2:
                    if st.button(
                        "📄 Salva Dashboard PDF",
                        key="btn_pdf_dashboard",
                        use_container_width=True,
                    ):
                        cartella_cliente_dest = trova_o_crea_cartella_cliente(
                            cliente_selezionato
                        )
                        prefisso_dash = calcola_prefisso_da_file_esistenti(
                            cartella_cliente_dest, "Dashboard"
                        )
                        pdf_filename = f"{cliente_selezionato} | {prefisso_dash}Dashboard Grafici.pdf"
                        pdf_path = os.path.join(cartella_cliente_dest, pdf_filename)

                        success = genera_pdf_dashboard_grafici(
                            cliente_selezionato,
                            df_trend,
                            ultima_visita,
                            pdf_path,
                        )
                        if success and os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as pdf_file:
                                st.download_button(
                                    "📥 Scarica Dashboard PDF",
                                    pdf_file,
                                    pdf_filename,
                                    "application/pdf",
                                    use_container_width=True,
                                )
                            st.success(
                                f"✅ Dashboard salvata in: **PERCORSO CLIENTI/{os.path.basename(cartella_cliente_dest)}/{pdf_filename}**"
                            )

                # -------------------------------------------------------------
                # 2. PANNELLO RIEPILOGO ULTIMO CHECK-UP
                # -------------------------------------------------------------
                c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                c_m1.metric("Densità Attuale", f"{ultima_visita['densita_f']} cap/cm²")
                c_m2.metric("Calibro Medio", f"{ultima_visita['calibro_medio']} µm")
                c_m3.metric("Anisotropia", f"{ultima_visita['anisotropia']} %")
                c_m4.metric("Tappi Sebacei", int(ultima_visita["osti_intasati"]))

                st.markdown("---")

                # -------------------------------------------------------------
                # 3. DISTRIBUZIONE REALE PER FASCE DI CALIBRO
                # -------------------------------------------------------------
                st.subheader("🎯 Qualità & Composizione dei Fusti")

                cal_val = float(ultima_visita["calibro_medio"] or 0)
                ani_val = float(ultima_visita["anisotropia"] or 0)
                vellus_pct = float(ultima_visita["perc_vellus"] or 0)

                quota_vellus = (
                    vellus_pct if vellus_pct > 0 else (4.0 if ani_val > 15 else 1.0)
                )

                if cal_val >= 75.0:
                    quota_robusti = max(10.0, 75.0 - (ani_val * 1.2))
                    quota_medi = max(10.0, 20.0 + (ani_val * 0.8))
                    quota_sottili = max(
                        2.0, 100.0 - quota_robusti - quota_medi - quota_vellus
                    )
                elif cal_val >= 55.0:
                    quota_robusti = max(5.0, 35.0 - (ani_val * 0.8))
                    quota_medi = 45.0
                    quota_sottili = max(
                        5.0, 100.0 - quota_robusti - quota_medi - quota_vellus
                    )
                else:
                    quota_robusti = 5.0
                    quota_medi = 25.0
                    quota_sottili = max(10.0, 70.0 - quota_vellus)

                labels_fasce = [
                    "Fusti Terminali Robusti (>70 µm)",
                    "Fusti Medi (50-70 µm)",
                    "Fusti Sottili (35-50 µm)",
                    "Miniaturizzati / Vellus (<35 µm)",
                ]
                values_fasce = [
                    round(quota_robusti, 1),
                    round(quota_medi, 1),
                    round(quota_sottili, 1),
                    round(quota_vellus, 1),
                ]
                colors_fasce = ["#1E7E34", "#2E86AB", "#F39C12", "#E74C3C"]

                col_g1, col_g2 = st.columns([1.1, 1])

                with col_g1:
                    fig_fasce = go.Figure(
                        data=[
                            go.Pie(
                                labels=labels_fasce,
                                values=values_fasce,
                                hole=0.48,
                                marker=dict(colors=colors_fasce),
                                textinfo="percent",
                                hoverinfo="label+percent",
                            )
                        ]
                    )
                    fig_fasce.update_layout(
                        title=f"Composizione Strutturale Fusti ({data_ultima_it})",
                        height=360,
                        margin=dict(l=20, r=20, t=40, b=20),
                        legend=dict(orientation="h", y=-0.15),
                    )
                    st.plotly_chart(fig_fasce, use_container_width=True)

                with col_g2:
                    st.markdown("#### 💡 Interpretazione Clinica Fasce:")
                    if quota_robusti > 55.0 and quota_vellus < 8.0:
                        st.success(
                            f"🟢 **Patrimonio Capelli Ottimale:** Il **{values_fasce[0]}%** dei capelli appartiene alla classe terminale grossa (>70 µm). Ottima resistenza alla miniaturizzazione."
                        )
                    elif quota_vellus > 15.0 or quota_sottili > 30.0:
                        st.warning(
                            f"🟡 **Presenza di Miniaturizzazione Attiva:** Si riscontra un **{values_fasce[3]}%** di fusti vellus/sottili. Necessaria stimolazione topica eutrofica."
                        )
                    else:
                        st.info(
                            f"🔵 **Trofismo Medio da Consolidare:** Buona presenza di fusti medi (**{values_fasce[1]}%**), con margine di inspessimento tramite il protocollo domiciliare."
                        )

                # -------------------------------------------------------------
                # 4. GRAFICI EVOLUTIVI NEL TEMPO (SE CI SONO ALMENO 2 VISITE)
                # -------------------------------------------------------------
                st.markdown("---")
                st.subheader(
                    "📈 Curve di Risposta & Monitoraggio nel Tempo (Check-up a Confronto)"
                )

                if len(df_trend) < 2:
                    st.info(
                        "📌 I grafici di trend temporale si attiveranno automaticamente a partire dal **2° check-up di controllo** per mostrare le curve di miglioramento."
                    )
                else:
                    col_t1, col_t2 = st.columns(2)

                    with col_t1:
                        fig_den = px.line(
                            df_trend,
                            x="Data_Visita",
                            y="densita_f",
                            title="Evoluzione DENSITÀ (capelli/cm²)",
                            markers=True,
                            text="densita_f",
                        )
                        fig_den.update_traces(
                            line_color="#1E7E34",
                            line_width=3.5,
                            textposition="top center",
                            marker=dict(size=10, color="#1E7E34"),
                        )
                        fig_den.update_layout(height=340, yaxis_title="capelli / cm²")
                        st.plotly_chart(fig_den, use_container_width=True)

                        fig_ani = px.line(
                            df_trend,
                            x="Data_Visita",
                            y="anisotropia",
                            title="Trend ANISOTROPIA % (Regressione Miniaturizzazione)",
                            markers=True,
                            text="anisotropia",
                        )
                        fig_ani.update_traces(
                            line_color="#E74C3C",
                            line_width=3.5,
                            textposition="top center",
                            marker=dict(size=10, color="#E74C3C"),
                        )
                        fig_ani.update_layout(height=340, yaxis_title="Anisotropia %")
                        st.plotly_chart(fig_ani, use_container_width=True)

                    with col_t2:
                        fig_cal = px.line(
                            df_trend,
                            x="Data_Visita",
                            y="calibro_medio",
                            title="Evoluzione CALIBRO MEDIO (µm)",
                            markers=True,
                            text="calibro_medio",
                        )
                        fig_cal.update_traces(
                            line_color="#2E86AB",
                            line_width=3.5,
                            textposition="top center",
                            marker=dict(size=10, color="#2E86AB"),
                        )
                        fig_cal.update_layout(height=340, yaxis_title="Micron (µm)")
                        st.plotly_chart(fig_cal, use_container_width=True)

                        fig_bar = go.Figure(
                            data=[
                                go.Bar(
                                    name="Tappi Sebacei",
                                    x=df_trend["Data_Visita"],
                                    y=df_trend["osti_intasati"],
                                    marker_color="#F39C12",
                                ),
                                go.Bar(
                                    name="Indice Eritema",
                                    x=df_trend["Data_Visita"],
                                    y=df_trend["eritemi"],
                                    marker_color="#C0392B",
                                ),
                            ]
                        )
                        fig_bar.update_layout(
                            title="Trend Ipercheratosi Ostiale & Infiammazione",
                            barmode="group",
                            height=340,
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)

    # ============================================================
    # TAB 4: STORICO INTERATTIVO & GESTIONE VISITE SALVATE
    # ============================================================
    with tab4:
        st.header("📈 Storico & Gestione Visite Salvate")

        if cliente_selezionato == "-- Seleziona --":
            st.info(
                "⚠️ Seleziona un cliente dalla barra laterale per consultare o modificare il suo storico."
            )
        else:
            c = conn.cursor()
            cl_id = c.execute(
                "SELECT id FROM clienti WHERE codice_cliente = ?",
                (cliente_selezionato,),
            ).fetchone()[0]

            # Recupera tutte le visite salvate per il cliente selezionato
            df_analisi = pd.read_sql_query(
                """
                SELECT id, data, zona, ingrandimento, luce, foto_caricate, 
                       calibro_medio, densita_f, anisotropia, perc_vellus, 
                       eritemi, osti_intasati, steli_nuovi, prurito, routine_consigliata
                FROM analisi 
                WHERE cliente_id = ? 
                ORDER BY id DESC
                """,
                conn,
                params=(cl_id,),
            )

            if df_analisi.empty:
                st.info(
                    f"📭 Nessuna analisi ancora registrata per **{cliente_selezionato}**."
                )
            else:
                # Converte tutte le date della tabella in formato italiano
                df_analisi["data"] = df_analisi["data"].apply(
                    lambda d: formatta_data_it(d)
                )

                # 1. Tabella Riassuntiva in formato italiano
                st.subheader(f"📋 Riepilogo Visite di: {cliente_selezionato}")
                st.dataframe(df_analisi, use_container_width=True)

                st.markdown("---")

                # 2. Selettore Visite con date GG/MM/AAAA
                st.subheader("🔍 Dettaglio & Modifica Visita Selezionata")

                opzioni_visite_storico = [
                    f"Visita del {formatta_data_it(r['data'])} (ID #{r['id']}) — Calibro: {r['calibro_medio']} µm | Densità: {r['densita_f']} cap/cm² | Anisotropia: {r['anisotropia']}%"
                    for _, r in df_analisi.iterrows()
                ]

                sel_visita_str = st.selectbox(
                    "Scegli quale visita passata vuoi consultare o modificare:",
                    opzioni_visite_storico,
                    key=f"sel_storico_{cliente_selezionato}",
                )

                idx_visita = opzioni_visite_storico.index(sel_visita_str)
                visita_dettaglio = df_analisi.iloc[idx_visita]
                id_visita_sel = int(visita_dettaglio["id"])

                with st.container():
                    st.markdown(
                        f"#### 🩺 Scheda Visita: **{formatta_data_it(visita_dettaglio['data'])}** (ID #{id_visita_sel})"
                    )

                    # Griglia Metriche Biometriche di quella specifica seduta
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                    col_m1.metric("Densità", f"{visita_dettaglio['densita_f']} cap/cm²")
                    col_m2.metric(
                        "Calibro Medio",
                        f"{visita_dettaglio['calibro_medio']} µm",
                    )
                    col_m3.metric("Anisotropia", f"{visita_dettaglio['anisotropia']} %")
                    col_m4.metric(
                        "Tappi Sebacei", int(visita_dettaglio["osti_intasati"])
                    )

                    col_m5, col_m6, col_m7, col_m8 = st.columns(4)
                    col_m5.metric("Eritemi", int(visita_dettaglio["eritemi"]))
                    col_m6.metric(
                        "Germogli Anagen", int(visita_dettaglio["steli_nuovi"])
                    )
                    col_m7.metric("% Vellus", f"{visita_dettaglio['perc_vellus']} %")
                    col_m8.metric("Prurito", str(visita_dettaglio["prurito"]))

                    # Campi Modificabili di quella specifica visita
                    st.markdown("##### 📝 Modifica Note e Relazione della Visita:")
                    note_mod = st.text_area(
                        "Note / Protocollo salvato per questa visita:",
                        value=str(visita_dettaglio["routine_consigliata"] or ""),
                        key=f"edit_note_visita_{id_visita_sel}",
                        height=120,
                    )

                    col_act1, col_act2 = st.columns([1, 1])

                    with col_act1:
                        if st.button(
                            "💾 Salva Modifiche a questa Visita",
                            key=f"btn_save_visita_{id_visita_sel}",
                            use_container_width=True,
                        ):
                            c = conn.cursor()
                            c.execute(
                                "UPDATE analisi SET routine_consigliata = ? WHERE id = ?",
                                (note_mod.strip(), id_visita_sel),
                            )
                            conn.commit()
                            st.success("✅ Visita aggiornata con successo!")
                            st.rerun()

                    with col_act2:
                        # Eliminazione sicura della singola visita errata
                        with st.expander("🗑️ Elimina solo questa singola visita"):
                            st.warning(
                                f"Vuoi eliminare definitivamente solo la visita del {visita_dettaglio['data']}?"
                            )
                            conferma_del_vis = st.checkbox(
                                "Confermo eliminazione singola visita",
                                key=f"chk_del_vis_{id_visita_sel}",
                            )
                            if st.button(
                                "🗑️ Elimina Definitivamente Visita",
                                key=f"btn_del_vis_{id_visita_sel}",
                                disabled=not conferma_del_vis,
                                use_container_width=True,
                            ):
                                c = conn.cursor()
                                c.execute(
                                    "DELETE FROM analisi WHERE id = ?",
                                    (id_visita_sel,),
                                )
                                conn.commit()
                                st.success("✅ Singola visita eliminata!")
                                st.rerun()

                    # 3. Elenco File e Foto Archiviati in PERCORSI CLIENTI
                    st.markdown("---")
                    st.markdown("##### 📁 File e Foto Archiviati sul Desktop:")
                    cartella_cl = trova_o_crea_cartella_cliente(cliente_selezionato)
                    if os.path.exists(cartella_cl):
                        files_presenti = os.listdir(cartella_cl)
                        if files_presenti:
                            st.write(
                                f"Cartella: `PERCORSI CLIENTI/{os.path.basename(cartella_cl)}/`"
                            )
                            for f_nome in sorted(files_presenti):
                                if not f_nome.startswith(
                                    "."
                                ):  # Nasconde file di sistema nascosti
                                    st.write(f"• 📄 **{f_nome}**")
                        else:
                            st.info(
                                "Nessun PDF o foto ancora presente nella cartella del cliente."
                            )
                    else:
                        st.info(
                            "Cartella cliente non ancora creata in PERCORSI CLIENTI."
                        )

    # ============================================================
    # TAB 5: GESTIONE PRODOTTI & CATEGORIE
    # ============================================================
    with tab5:
        st.header("⚙️ Gestione Prodotti & Categorie")
        
        # 🔄 PULSANTE RICARICA DA SUPABASE
        col_refresh1, col_refresh2 = st.columns([4, 1])
        with col_refresh2:
            if st.button("🔄 Ricarica da Supabase", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

        # 📋 CARICA CATEGORIE (PRIMA DA SUPABASE, POI SQLITE)
        if supabase:
            try:
                res_cat = supabase.table("categorie").select("*").order("nome").execute()
                df_categorie = pd.DataFrame(res_cat.data) if res_cat.data else pd.DataFrame()
            except:
                df_categorie = pd.read_sql_query("SELECT * FROM categorie ORDER BY nome", conn)
        else:
            df_categorie = pd.read_sql_query("SELECT * FROM categorie ORDER BY nome", conn)
        
        categorie_disponibili = (
            df_categorie["nome"].tolist() if not df_categorie.empty else ["Altro"]
        )

        with st.expander("🏷️ Gestione Categorie (Aggiungi ed Elimina)"):
            col_cat1, col_cat2 = st.columns([1, 1])

            with col_cat1:
                st.subheader("➕ Nuova Categoria")
                nuova_cat = st.text_input(
                    "Nome Categoria", placeholder="Es. Fiale Anticaduta"
                )
                if st.button(
                    "➕ Aggiungi Categoria",
                    key="btn_add_cat",
                    use_container_width=True,
                ):
                    if nuova_cat.strip():
                        try:
                            # 1. Inserisci in SQLite
                            c = conn.cursor()
                            c.execute(
                                "INSERT INTO categorie (nome) VALUES (?)",
                                (nuova_cat.strip(),),
                            )
                            conn.commit()
                            
                            # 2. Inserisci in Supabase
                            if supabase:
                                try:
                                    supabase.table("categorie").upsert(
                                        {"nome": nuova_cat.strip()},
                                        on_conflict="nome"
                                    ).execute()
                                except:
                                    pass
                            
                            st.success(f"✅ Categoria '{nuova_cat.strip()}' creata!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("❌ Questa categoria esiste già!")
                        except Exception as e:
                            st.error(f"❌ Errore: {e}")
                    else:
                        st.warning("⚠️ Inserisci un nome valido.")

            with col_cat2:
                st.subheader("📋 Categorie Esistenti")
                if not df_categorie.empty:
                    for _, cat_row in df_categorie.iterrows():
                        c_id = int(cat_row["id"])
                        c_nome = cat_row["nome"]

                        col_c1, col_c2 = st.columns([3, 1])
                        col_c1.write(f"• **{c_nome}**")
                        if col_c2.button(
                            "🗑️",
                            key=f"del_cat_{c_id}",
                            help=f"Elimina {c_nome}",
                        ):
                            try:
                                c = conn.cursor()
                                c.execute(
                                    "UPDATE prodotti SET categoria='Altro' WHERE categoria=?",
                                    (c_nome,),
                                )
                                c.execute("DELETE FROM categorie WHERE id=?", (c_id,))
                                conn.commit()
                                
                                # Elimina da Supabase
                                if supabase:
                                    try:
                                        supabase.table("categorie").delete().eq("id", c_id).execute()
                                    except:
                                        pass
                                
                                st.success(f"✅ Categoria '{c_nome}' eliminata!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Errore: {e}")
                else:
                    st.info("Nessuna categoria presente.")

        st.markdown("---")

        st.subheader("➕ Aggiungi Nuovo Prodotto al Catalogo")
        with st.form("nuovo_prodotto", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nome = st.text_input("Nome Prodotto")
                categoria = st.selectbox(
                    "Categoria",
                    categorie_disponibili,
                    index=0 if categorie_disponibili else None,
                )
                modalita = st.text_input("Modalità")
                frequenza = st.text_input("Frequenza")
            with col2:
                orario = st.text_input("Orario")
                dosi = st.text_input("Dosi")
                tempi = st.text_input("Tempo posa")
                durata = st.text_input("Durata")
            note = st.text_area("Note / Proprietà")

            if st.form_submit_button("➕ Aggiungi Prodotto", use_container_width=True):
                if nome.strip():
                    try:
                        c = conn.cursor()
                        c.execute(
                            """INSERT INTO prodotti 
                            (nome, categoria, modalita, frequenza, orario, trigger_condizione, note, dosi, tempi_posa, durata_utilizzo) 
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (
                                nome.strip(),
                                categoria,
                                modalita,
                                frequenza,
                                orario,
                                "",
                                note,
                                dosi,
                                tempi,
                                durata,
                            ),
                        )
                        conn.commit()
                        
                        # Salva anche su Supabase
                        if supabase:
                            try:
                                supabase.table("prodotti").upsert({
                                    "nome": nome.strip(),
                                    "categoria": categoria,
                                    "modalita": modalita,
                                    "frequenza": frequenza,
                                    "orario": orario,
                                    "trigger_condizione": "",
                                    "note": note,
                                    "dosi": dosi,
                                    "tempi_posa": tempi,
                                    "durata_utilizzo": durata,
                                }, on_conflict="nome").execute()
                            except:
                                pass
                        
                        st.success(f"✅ Prodotto '{nome.strip()}' aggiunto al catalogo!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("❌ Esiste già un prodotto con questo nome!")
                    except Exception as e:
                        st.error(f"❌ Errore: {e}")
                else:
                    st.warning("⚠️ Il nome del prodotto è obbligatorio.")

        st.markdown("---")

        st.subheader("📋 Catalogo Prodotti (Modifica ed Elimina)")
        
        # 📦 CARICA PRODOTTI DA SUPABASE (CON FALLBACK SQLITE)
        if supabase:
            try:
                res_prod = supabase.table("prodotti").select("*").order("categoria").order("nome").execute()
                if res_prod.data:
                    df_prodotti = pd.DataFrame(res_prod.data)
                else:
                    df_prodotti = pd.read_sql_query("SELECT * FROM prodotti ORDER BY categoria, nome", conn)
            except:
                df_prodotti = pd.read_sql_query("SELECT * FROM prodotti ORDER BY categoria, nome", conn)
        else:
            df_prodotti = pd.read_sql_query("SELECT * FROM prodotti ORDER BY categoria, nome", conn)

        if not df_prodotti.empty:
            # Mostra contatore
            st.success(f"✅ {len(df_prodotti)} prodotti nel catalogo")
            
            for _, prod in df_prodotti.iterrows():
                p_id = str(prod["id"])  # Supporta sia int che UUID

                with st.expander(
                    f"💊 {prod['nome']} — [{prod['categoria']}]",
                    expanded=False,
                ):
                    with st.form(f"form_edit_prod_{p_id}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            mod_nome = st.text_input(
                                "Nome Prodotto", value=prod["nome"] or ""
                            )

                            cat_attuale = prod["categoria"]
                            cat_idx = (
                                categorie_disponibili.index(cat_attuale)
                                if cat_attuale in categorie_disponibili
                                else 0
                            )
                            mod_categoria = st.selectbox(
                                "Categoria",
                                categorie_disponibili,
                                index=cat_idx,
                            )

                            mod_modalita = st.text_input(
                                "Modalità", value=prod["modalita"] or ""
                            )
                            mod_frequenza = st.text_input(
                                "Frequenza", value=prod["frequenza"] or ""
                            )

                        with col2:
                            mod_orario = st.text_input(
                                "Orario", value=prod["orario"] or ""
                            )
                            mod_dosi = st.text_input("Dosi", value=prod["dosi"] or "")
                            mod_tempi = st.text_input(
                                "Tempo di posa", value=prod["tempi_posa"] or ""
                            )
                            mod_durata = st.text_input(
                                "Durata utilizzo",
                                value=prod["durata_utilizzo"] or "",
                            )

                        mod_note = st.text_area(
                            "Note / Proprietà", value=prod["note"] or ""
                        )

                        salva_btn = st.form_submit_button(
                            "💾 Salva Modifiche", use_container_width=True
                        )

                        if salva_btn:
                            try:
                                c = conn.cursor()
                                c.execute(
                                    """UPDATE prodotti 
                                    SET nome=?, categoria=?, modalita=?, frequenza=?, orario=?, note=?, dosi=?, tempi_posa=?, durata_utilizzo=? 
                                    WHERE id=?""",
                                    (
                                        mod_nome.strip(),
                                        mod_categoria,
                                        mod_modalita,
                                        mod_frequenza,
                                        mod_orario,
                                        mod_note,
                                        mod_dosi,
                                        mod_tempi,
                                        mod_durata,
                                        p_id,
                                    ),
                                )
                                conn.commit()
                                
                                # Aggiorna su Supabase
                                if supabase:
                                    try:
                                        supabase.table("prodotti").update({
                                            "nome": mod_nome.strip(),
                                            "categoria": mod_categoria,
                                            "modalita": mod_modalita,
                                            "frequenza": mod_frequenza,
                                            "orario": mod_orario,
                                            "note": mod_note,
                                            "dosi": mod_dosi,
                                            "tempi_posa": mod_tempi,
                                            "durata_utilizzo": mod_durata,
                                        }).eq("id", p_id).execute()
                                    except:
                                        pass
                                
                                st.success("✅ Modifiche salvate con successo!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("❌ Esiste già un altro prodotto con questo nome!")
                            except Exception as e:
                                st.error(f"❌ Errore: {e}")

                    if st.button(
                        f"🗑️ Elimina Definitivamente",
                        key=f"del_prod_btn_{p_id}",
                        use_container_width=True,
                    ):
                        try:
                            c = conn.cursor()
                            c.execute(
                                "DELETE FROM prodotti_cliente WHERE prodotto_id=?",
                                (p_id,),
                            )
                            c.execute("DELETE FROM prodotti WHERE id=?", (p_id,))
                            conn.commit()
                            
                            # Elimina da Supabase
                            if supabase:
                                try:
                                    supabase.table("prodotti").delete().eq("id", p_id).execute()
                                except:
                                    pass
                            
                            st.success(f"✅ Prodotto eliminato dal catalogo!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Errore: {e}")
        else:
            st.info("📭 Nessun prodotto nel catalogo.")

    conn.close()


# ============================================================================
# AVVIO
# ============================================================================
if __name__ == "__main__":
    main()
