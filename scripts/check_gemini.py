"""Confere se a chave do Gemini funciona e lista os modelos disponíveis.

Uso:
    python -m scripts.check_gemini
    python -m scripts.check_gemini --model gemini-2.5-flash   (testa outro modelo)
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import errors


def main() -> None:
    load_dotenv()  # lê o arquivo .env da raiz do projeto
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--list", action="store_true", help="lista os modelos 'flash'")
    args = parser.parse_args()

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY não encontrada. Crie o arquivo .env (veja .env.example).")

    client = genai.Client(api_key=key)

    if args.list:
        print("Modelos 'flash' disponíveis para a sua chave:")
        try:
            for m in client.models.list():
                actions = getattr(m, "supported_actions", None) or []
                if "flash" in m.name and "generateContent" in actions:
                    print("  ", m.name.removeprefix("models/"))
        except errors.APIError as exc:
            # A listagem às vezes falha nas páginas seguintes; não afeta o uso do modelo.
            print(f"   (listagem interrompida: {exc.code})")

    model = args.model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    print(f"\nTestando o modelo {model}...")
    response = client.models.generate_content(model=model, contents="Responda apenas: OK")
    print("Resposta:", response.text.strip())


if __name__ == "__main__":
    main()
