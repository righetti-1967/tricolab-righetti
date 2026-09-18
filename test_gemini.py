"""
Test di analisi tricologica con Gemini Vision.
Uso: python test_gemini.py "/path/della/foto.jpg"
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.tricologia_ai import analizza_immagine_gemini, sintesi_narrativa_da_json


def main():
    if len(sys.argv) < 2:
        print("Uso: python test_gemini.py <path_foto>")
        sys.exit(1)

    foto_path = Path(sys.argv[1])
    if not foto_path.exists():
        print(f"❌ File non trovato: {foto_path}")
        sys.exit(1)

    try:
        import streamlit as st
        api_key = st.secrets["GEMINI_API_KEY"]
        print("✅ API key letta da .streamlit/secrets.toml")
    except Exception as e:
        print(f"❌ Errore lettura secrets: {e}")
        sys.exit(1)

    print(f"📷 Foto: {foto_path} ({foto_path.stat().st_size / 1024:.1f} KB)")
    with open(foto_path, "rb") as f:
        image_bytes = f.read()

    print(f"🔄 Analisi in corso con gemini-3.5-flash...")
    risultato = analizza_immagine_gemini(
        image_bytes=image_bytes,
        api_key=api_key,
        lente="50x",           # "50x" o "200x"
        luce="Bianca",         # "Bianca", "Polarizzata", "Mista"
        zona="Vertice",        # "Frontale", "Parietale", "Vertice", "Temporale", "Occipitale", "Multi-zona"
        sesso="Uomo",          # "Uomo" o "Donna"
        etnia="Caucasica",     # "Caucasica", "Africana", "Mediterranea", "Non specificata"
        eta=40,                # numero intero
    )

    print("\n" + "=" * 70)
    print("📊 RISULTATO JSON")
    print("=" * 70)
    print(json.dumps(risultato, indent=2, ensure_ascii=False))

    if "errore" not in risultato:
        print("\n" + "=" * 70)
        print("📝 SINTESI NARRATIVA (per report PDF)")
        print("=" * 70)
        print(sintesi_narrativa_da_json(risultato))

        output_file = Path("test_output.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(risultato, f, indent=2, ensure_ascii=False)
        print(f"\n💾 JSON salvato in: {output_file}")


if __name__ == "__main__":
    main()
