"""
Modulo isolato per analisi tricologica con Gemini Vision.
Standard: approccio dermo-fitocosmetico Righetti Since 1967
"""

import json
from typing import Optional
from google import genai
from google.genai import types


MODELLO_DEFAULT = "gemini-3.5-flash"


PROMPT_SISTEMA = '''
Sei un consulente esperto in dermotricologia fitocosmetica e tricologia
olistica, con oltre 20 anni di esperienza in trattamenti topici naturali,
riequilibrio del microbiota del cuoio capelluto, integrazione nutraceutica
e approccio olistico al benessere dei capelli. Operi nello Studio
Tricologico Righetti Since 1967, che NON e uno studio medico ma un centro
dermo-fitocosmetico specializzato in percorsi di cura naturali.

Il tuo compito e analizzare immagini tricoscopiche e restituire una
valutazione strutturata in formato JSON, secondo lo schema fornito.

REGOLE FONDAMENTALI:
1. Rispondi SEMPRE e SOLO con un oggetto JSON valido conforme allo schema.
2. Non inventare mai dati non osservabili direttamente da una immagine.
   Se un parametro non e valutabile, restituisci null e spiegalo in note_qualita.
3. Questo Studio NON e medico. Non prescrivere mai farmaci (minoxidil,
   finasteride, antiandrogeni, cortisonici, ecc.).
4. Non suggerire esami ematochimici come prescrizione, ma semmai come
   approfondimento consigliabile in accordo con il medico curante.
5. L approccio e dermo-fitocosmetico e olistico: trattamenti topici naturali,
   fitoterapia, integratori, probiotici, riequilibrio del microbiota,
   gestione dello stress, alimentazione, stile di vita.
6. Le raccomandazioni devono essere propositive e non medicalizzanti.
7. Evita termini come terapia, farmaco, prescrizione, diagnosi. Usa:
   protocollo, rituale di cura, percorso, osservazione, indicazione cosmetica.
8. La confidenza deve essere onesta.

CLASSIFICAZIONE DELLA IMMAGINE:
- 50x: si vedono piu unita follicolari, diversi fusti nello stesso campo visivo.
- 200x: si vede in dettaglio una singola unita follicolare o pochi fusti.
- Luce bianca: colori naturali, cute rosea o giallastra.
- Luce polarizzata: riflessi luminosi, colori piu saturi.

PARAMETRI DA VALUTARE A 50x:
- Densita follicolare (capelli per cm2): vedi sezione DENSITA FOLLICOLARE.
- Numero medio di capelli per unita follicolare.
- Anisotricchia (variazione diametro maggiore del 20 percento).
- Yellow dots: assenti / rare / moderate / numerose.
- Peli vellus / miniaturizzati.
- Tabbi sebacei (follicular plugs): assenti / rari / moderati / numerosi.
- Eritema perifollicolare, desquamazione.

PARAMETRI DA VALUTARE A 200x:
- Forma del bulbo: normale / miniaturizzato / distrofico / misto.
- Stato delle guaine: integre / assottigliate / assenti / alterate.
- Tabbi sebacei (follicular plugs): assenti / rari / moderati / numerosi.
- Follicoli silenti (vuoti): assenti / rari / moderati / numerosi.
- Cheratinizzazione: normale / alterata / irregolare.
- Segni di infiammazione.
- NON calcolare la densita follicolare a 200x (restituisci sempre null).

=== DENSITA FOLLICOLARE (SOLO PER IMMAGINI A 50x) ===

L operatore ti fornisce i seguenti dati del paziente:
- Sesso: {sesso}
- Etnia: {etnia}
- Eta: {eta} anni
- Zona anatomica: {zona}

Usa la tabella sottostante per scegliere il RANGE DI RIFERIMENTO NORMALE,
poi confronta cio che vedi nella immagine con quel range e fornisci
una STIMA NUMERICA PRECISA (numero singolo, non intervallo) della densita.

L etnia principale dello Studio Righetti Since 1967 e quella CAUCASICA
(Europa, Italia in particolare). Le altre etnie sono casi rari e vanno
usate solo se l operatore le ha selezionate esplicitamente.

=== ETNIA CAUCASICA (principale) ===

ZONE PRINCIPALI (Frontale, Parietale, Vertice):
- minore di 120 capelli/cm2: densita MOLTO BASSA
- 120-124 capelli/cm2: densita BASSA
- 125-199 capelli/cm2: densita NORMALE
- maggiore o uguale a 200 capelli/cm2: densita ALTA

ZONA TEMPORALE:
- minore di 100 capelli/cm2: densita MOLTO BASSA
- 100-124 capelli/cm2: densita BASSA
- 125-179 capelli/cm2: densita NORMALE
- maggiore o uguale a 180 capelli/cm2: densita ALTA

ZONA OCCIPITALE (SOLO PER DONNE):
- minore di 140 capelli/cm2: densita MOLTO BASSA
- 140-159 capelli/cm2: densita BASSA
- 160-229 capelli/cm2: densita NORMALE
- maggiore o uguale a 230 capelli/cm2: densita ALTA

ATTENZIONE ZONA OCCIPITALE NELL UOMO:
La zona occipitale nell uomo e la zona DONATRICE, NON soggetta a
miniaturizzazione androgenetica. Se il sesso e Uomo e la zona e occipitale:
- NON fornire un valore di densita (restituisci null)
- Aggiungi in note_qualita: "Zona occipitale non valutata per densita:
  zona donatrice, non soggetta a miniaturizzazione androgenetica nell uomo."

=== ETNIA AFRICANA (casi rari) ===
- Frontale: 133-187 capelli/cm2
- Parietale/Vertice/Temporale: 105-173 capelli/cm2
- Occipitale: 148-160 capelli/cm2

=== ETNIA MEDITERRANEA (casi rari) ===
- Frontale: 161-218 capelli/cm2
- Parietale/Vertice: 149-213 capelli/cm2
- Temporale: 130-180 capelli/cm2
- Occipitale: 149-213 capelli/cm2

=== ETNIA NON SPECIFICATA (casi rari) ===
- Usa un range generico 120-220 capelli/cm2 per tutte le zone.
- Segnala in note_qualita che manca il dato etnico.

REGOLE PER LA DENSITA:
1. Se la immagine e a 200x: restituisci SEMPRE null per densita_follicolare_per_cm2.
2. Se la immagine e a 50x:
   - Scegli il range in base a etnia + zona + sesso.
   - Fornisci un NUMERO PRECISO (esempio 165) come stima della densita.
   - Aggiungi densita_giudizio con valore:
     "molto_bassa" | "bassa" | "normale" | "alta"
   - Nel caso della zona occipitale maschile, restituisci null e nota_qualita.
3. I range vanno SEMPRE contestualizzati da eta e sesso:
   un uomo di 50 anni con 130 capelli/cm2 al vertice puo essere nella
   norma per eta, mentre una donna di 25 anni con 130 capelli/cm2
   al vertice e probabilmente in densita bassa.
OSSERVAZIONI DIFFERENZIALI (pattern osservabili, NON diagnosi):
- Pattern osservato: AGA, TE, AA, FFA, normale, misto, non determinabile.
  Queste sigle servono per classificazione descrittiva del pattern osservato.
- Severita: lieve, moderata, avanzata, non valutabile.
- Segni chiave osservati.
- Osservazioni differenziali in chiave cosmetica/olistica.

RACCOMANDAZIONI (approccio Righetti Since 1967):
Le raccomandazioni devono essere dermo-fitocosmetiche e olistiche, ad esempio:
- Protocolli topici fitocosmetici (lozioni, sieri, maschere)
- Integrazione nutraceutica (vitamine, minerali, aminoacidi solforati, antiossidanti)
- Probiotici e riequilibrio del microbiota cutaneo
- Gestione dello stress e del sonno
- Indicazioni alimentari di supporto
- Follow-up tricoscopico cosmetico
- Riferimento al medico curante SOLO per conferma clinica, non per prescrizioni

RIFERIMENTI TECNICI:
- Anisotricchia maggiore del 20 percento in zona androgeno-dipendente:
  segno osservabile di pattern AGA.
- Yellow dots: tipici di pattern AA, presenti anche in AGA avanzata e TE cronico.
- Tabbi sebacei prominenti: associati a squilibri del microbiota e seborrea.
- Miniaturizzazione e riduzione densita: segni cardinali di pattern AGA.
- Eritema perifollicolare e desquamazione: possibile squilibrio del microbiota.

Restituisci SOLO il JSON conforme allo schema fornito.
'''


SCHEMA_JSON = {
    "type": "object",
    "properties": {
        "metadati_immagine": {
            "type": "object",
            "properties": {
                "tipo_immagine": {"type": "string", "enum": ["50x", "200x", "sconosciuto"]},
                "tipo_luce": {"type": "string", "enum": ["bianca", "polarizzata", "sconosciuta"]},
                "zona_anatomica": {"type": "string"},
                "qualita_immagine": {"type": "string", "enum": ["ottima", "buona", "sufficiente", "scarsa"]},
                "note_qualita": {"type": "string"},
            },
            "required": ["tipo_immagine", "tipo_luce", "zona_anatomica", "qualita_immagine"],
        },
        "analisi_50x": {
            "type": "object",
            "properties": {
                "densita_follicolare_per_cm2": {"type": "integer", "nullable": True},
                "densita_giudizio": {"type": "string", "enum": ["molto_bassa", "bassa", "normale", "alta", "non_valutabile"]},
                "capelli_per_unita_follicolare_media": {"type": "number", "nullable": True},
                "anisotricchia_presente": {"type": "boolean"},
                "anisotricchia_percentuale": {"type": "integer", "nullable": True},
                "anisotricchia_distribuzione": {"type": "string"},
                "yellow_dots_quantita": {"type": "string"},
                "peli_vellus_presenti": {"type": "boolean"},
                "peli_vellus_percentuale": {"type": "integer", "nullable": True},
                "eritema_perifollicolare": {"type": "boolean"},
                "desquamazione": {"type": "boolean"},
                "tabbi_sebacei_quantita": {"type": "string"},
                "stato_generale": {"type": "string"},
            },
        },
        "analisi_200x": {
            "type": "object",
            "properties": {
                "forma_bulbo": {"type": "string"},
                "stato_guaine": {"type": "string"},
                "tabbi_sebacei_quantita": {"type": "string"},
                "follicoli_silenti_quantita": {"type": "string"},
                "cheratinizzazione": {"type": "string"},
                "segni_infiammazione": {"type": "boolean"},
                "note_dettaglio": {"type": "string"},
            },
        },
        "sintesi_clinica": {
            "type": "object",
            "properties": {
                "pattern_osservato": {"type": "string"},
                "severita_stimata": {"type": "string"},
                "segni_chiave": {"type": "array", "items": {"type": "string"}},
                "osservazioni_differenziali": {"type": "array", "items": {"type": "string"}},
                "raccomandazioni": {"type": "array", "items": {"type": "string"}},
                "confidenza_analisi": {"type": "number"},
                "limitazioni": {"type": "string"},
            },
            "required": ["pattern_osservato", "severita_stimata", "confidenza_analisi"],
        },
    },
    "required": ["metadati_immagine", "sintesi_clinica"],
}


def analizza_immagine_gemini(
    image_bytes: bytes,
    api_key: str,
    lente: str = "50x",
    luce: str = "Bianca",
    zona: str = "Vertice",
    sesso: str = "Uomo",
    etnia: str = "Non specificata",
    eta: int = 40,
    dati_opencv: Optional[dict] = None,
    modello: str = MODELLO_DEFAULT,
    mime_type: str = "image/jpeg",
) -> dict:
    """Analizza una immagine tricoscopica con Gemini Vision."""
    try:
        prompt_sistema_compilato = PROMPT_SISTEMA.format(
            sesso=sesso,
            etnia=etnia,
            eta=eta,
            zona=zona,
        )

        contesto_extra = ""
        if dati_opencv:
            contesto_extra = (
                "\n\nDATI GIA CALCOLATI DA OPENCV:\n"
                f"- Eritema diffuso: {dati_opencv.get('eritema_diffuso', 'N/D')}\n"
                f"- Tappi sebacei: {dati_opencv.get('tappi_sebacei', 'N/D')}\n"
                f"- Follicoli dormienti: {dati_opencv.get('follicoli_dormienti', 'N/D')}\n"
                f"- Steli anagen: {dati_opencv.get('steli_anagen', 'N/D')}\n"
                f"- Steli vellus: {dati_opencv.get('steli_vellus', 'N/D')}\n"
                f"- Calibro medio: {dati_opencv.get('calibro_medio', 'N/D')} um\n"
                f"- Anisotropia: {dati_opencv.get('anisotropia', 'N/D')} percento\n"
            )

        prompt_utente = (
            "Analizza questa immagine tricoscopica.\n\n"
            "CONTESTO:\n"
            f"- Ingrandimento: {lente}\n"
            f"- Luce: {luce}\n"
            f"- Zona: {zona}\n"
            f"- Sesso: {sesso}\n"
            f"- Etnia: {etnia}\n"
            f"- Eta: {eta} anni\n"
            f"{contesto_extra}\n\n"
            "Compila TUTTI i campi dello schema JSON.\n"
            "Per la densita (solo se 50x): usa il range etnia+zona e fornisci un numero preciso.\n"
            "Le raccomandazioni devono essere in stile Righetti Since 1967: "
            "dermo-fitocosmetiche, olistiche, senza farmaci ne prescrizioni mediche."
        )

        client = genai.Client(api_key=api_key)
        contenuto = [
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt_utente,
        ]

        # === CHIAMATA A GEMINI CON RETRY E FALLBACK AUTOMATICO ===
        import time

        # Lista modelli: primo = principale, secondo = fallback
        MODELLI_FALLBACK = [modello, "gemini-2.5-flash"]
        MAX_TENTATIVI = 4
        ATTESE = [0, 3, 8, 15]  # secondi tra i tentativi
        errore_finale = None

        for idx_modello, modello_corrente in enumerate(MODELLI_FALLBACK):
            if idx_modello > 0:
                print(f"[fallback] passo al modello secondario: {modello_corrente}")

            for tentativo in range(MAX_TENTATIVI):
                try:
                    if ATTESE[tentativo] > 0:
                        print(f"[retry {tentativo}/{MAX_TENTATIVI-1}] modello={modello_corrente}, attendo {ATTESE[tentativo]}s...")
                        time.sleep(ATTESE[tentativo])

                    response = client.models.generate_content(
                        model=modello_corrente,
                        contents=contenuto,
                        config=types.GenerateContentConfig(
                            system_instruction=prompt_sistema_compilato,
                            response_mime_type="application/json",
                            response_schema=SCHEMA_JSON,
                            temperature=0.2,
                        ),
                    )

                    # Successo: esci e restituisci
                    return json.loads(response.text)

                except Exception as e:
                    msg = str(e)
                    # Riconosci errori temporanei che vale la pena ritentare
                    temporaneo = any([
                        "503" in msg,
                        "UNAVAILABLE" in msg,
                        "429" in msg,
                        "RESOURCE_EXHAUSTED" in msg,
                        "timeout" in msg.lower(),
                        "connection" in msg.lower(),
                        "overloaded" in msg.lower(),
                        "high demand" in msg.lower(),
                    ])

                    if temporaneo and tentativo < MAX_TENTATIVI - 1:
                        errore_finale = e
                        print(f"[retry] errore temporaneo ({modello_corrente}): {msg[:120]}...")
                        continue
                    elif temporaneo and idx_modello == 0:
                        # Esauriti i tentativi sul primo modello: passa al fallback
                        errore_finale = e
                        print(f"[fallback] {modello_corrente} non disponibile, provo il modello secondario...")
                        break  # esci dal loop interno, vai al modello successivo
                    else:
                        # Errore non temporaneo o ultimo modello: rilancia
                        raise

        # Se arriviamo qui, tutti i modelli e i tentativi sono falliti
        raise errore_finale if errore_finale else Exception("Tutti i modelli e i tentativi falliti")

    except json.JSONDecodeError as e:
        return {"errore": "JSON non valido", "dettagli": str(e)}
    except Exception as e:
        return {"errore": "Errore chiamata Gemini", "dettagli": str(e), "tipo": type(e).__name__}


def sintesi_narrativa_da_json(analisi: dict) -> str:
    """Trasforma il JSON in testo narrativo per il report."""
    if "errore" in analisi:
        return f"[Errore: {analisi.get('errore')}]"

    metadati = analisi.get("metadati_immagine", {})
    sintesi = analisi.get("sintesi_clinica", {})
    a50 = analisi.get("analisi_50x") or {}
    a200 = analisi.get("analisi_200x") or {}

    righe = []
    righe.append(
        f"Inquadramento: immagine {metadati.get('tipo_immagine', 'N/D')}, "
        f"luce {metadati.get('tipo_luce', 'N/D')}, "
        f"zona {metadati.get('zona_anatomica', 'N/D')}."
    )

    if a50:
        erit = "presente" if a50.get("eritema_perifollicolare") else "assente"
        desq = "presente" if a50.get("desquamazione") else "assente"
        righe.append(f"Cute: eritema {erit}, desquamazione {desq}.")

    # Tappi sebacei: cercali in a50 o a200 (vanno valutati a entrambi gli ingrandimenti)
    tappi_q = None
    if a50 and a50.get('tabbi_sebacei_quantita'):
        tappi_q = a50.get('tabbi_sebacei_quantita')
    if a200 and a200.get('tabbi_sebacei_quantita'):
        tappi_q = a200.get('tabbi_sebacei_quantita')

    # Follicoli silenti: solo a 200x
    silenti_q = a200.get('follicoli_silenti_quantita') if a200 else None

    if tappi_q or silenti_q:
        partes = []
        if tappi_q:
            partes.append(f"tappi {tappi_q}")
        if silenti_q:
            partes.append(f"follicoli silenti {silenti_q}")
        righe.append("Osti: " + ", ".join(partes) + ".")

    if a50 and a50.get("anisotricchia_presente"):
        righe.append(
            f"Fusti: anisotricchia {a50.get('anisotricchia_percentuale', 'N/D')} percento, "
            f"distribuzione {a50.get('anisotricchia_distribuzione', 'N/D')}."
        )

    if a50:
        dens = a50.get("densita_follicolare_per_cm2")
        giud = a50.get("densita_giudizio", "")
        if dens is not None:
            righe.append(f"Densita: {dens} cap/cm2 ({giud}).")

    righe.append(
        f"Pattern: {sintesi.get('pattern_osservato', 'N/D')} "
        f"({sintesi.get('severita_stimata', 'N/D')})."
    )
    righe.append(f"Confidenza: {sintesi.get('confidenza_analisi', 0):.2f}.")

    racc = sintesi.get("raccomandazioni", [])
    if racc:
        righe.append("Raccomandazioni: " + "; ".join(racc[:3]) + ".")

    return "\n".join(righe)
