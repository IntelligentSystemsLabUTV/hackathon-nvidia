# Nebius vision smoke test

Questo test verifica il primo collegamento del progetto:

```text
immagine locale → modello NVIDIA su Nebius → descrizione JSON
```

Lo script vive in `scripts/`, perché è codice del progetto hackathon. La cartella
`tools/agenticros` contiene invece il submodule AgenticROS e non va usata per
utility specifiche di questa demo.

## Modelli scelti

La pipeline usa due modelli sul public endpoint di Nebius:

- `openbmb/MiniCPM-V-4_5` per estrarre dall'immagine una descrizione strutturata;
- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` per ragionamento, scelta delle azioni
  e tool calling.

`Nemotron-Nano-V2-12b` sarebbe il modello NVIDIA vision preferibile, ma nel
catalogo corrente è disponibile soltanto tramite endpoint dedicato. Non compare
nell'elenco restituito dal public endpoint per questa API key. Anche
`Nemotron-3-Nano-Omni` compare nel catalogo generale, ma non esiste nel public
endpoint interrogato e restituisce HTTP 404.

MiniCPM-V 4.5 è il modello vision accessibile più piccolo fra quelli elencati
dalla chiave ed è quindi il default per i test. Nemotron 3 Nano costa circa
$0.06 per milione di token in input e $0.24 per milione in output secondo il
catalogo Token Factory, e mantiene un ruolo sostanziale nel progetto: riceve la
scena osservata, decide quale evidenza raccogliere e invoca le capability
AgenticROS.

I prezzi non sono inclusi nel repository perché possono cambiare. La scelta
definitiva va fatta dopo aver misurato qualità, latenza e consumo sulle stesse
immagini Gazebo.

## Configurazione

Creare un ambiente Python e installare le due dipendenze:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r scripts/requirements-nebius.txt
```

Inserire la chiave nel file `.env` alla radice:

```dotenv
NEBIUS_API_KEY=la_chiave_reale
```

`.env` è già escluso da Git. Non inserire la chiave in `.env.example`, nei log
o negli argomenti della shell.

## Verifica dei modelli disponibili

Prima della chiamata vision, verificare gli ID realmente accessibili:

```bash
python scripts/nebius_vision_smoke.py --list-models
```

Per filtrare l'elenco:

```bash
python scripts/nebius_vision_smoke.py --list-models --filter vision
python scripts/nebius_vision_smoke.py --list-models --filter nemotron
```

Se un ID differisce, aggiornare `NEBIUS_VISION_MODEL` o
`NEBIUS_REASONING_MODEL` in `.env`.

## Invio di un'immagine

```bash
python scripts/nebius_vision_smoke.py /percorso/immagine.png
```

Per provare un altro modello vision senza modificare `.env`:

```bash
python scripts/nebius_vision_smoke.py \
  --model google/gemma-3-27b-it \
  /percorso/immagine.png
```

Lo script accetta JPEG, PNG e WebP, chiede un risultato JSON e mostra su stderr
modello, latenza e request ID. Non stampa la chiave API.

Il test è superato quando il JSON descrive correttamente gli oggetti visibili,
non inventa passaggi assenti e indica quando serve una nuova osservazione.
