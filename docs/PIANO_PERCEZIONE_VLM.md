# Piano: percezione senza YOLO (solo modello vision) e aggiornamento di YOLO

> **Stato: implementato** il 12 ottobre 2026 (diff applicato, configurazione e documentazione aggiornate). Riepilogo delle modifiche: [CHANGELOG_PERCEZIONE_VLM.md](CHANGELOG_PERCEZIONE_VLM.md). Questo documento resta come riferimento del metodo e delle misure. Dopo l'implementazione il default è diventato `NEBIUS_PERCEPTION=vlm` (senza YOLO); dove qui sotto si legge "`yolo` (default)" vale la scelta iniziale del piano.

Piano operativo per l'agente che implementa. Nasce da uno studio con prove in simulazione (12 ottobre 2026). Base: repo `751073b`, submodule `tools/agenticros` `fbcb9a7`.

Il prototipo di riferimento è [`PIANO_PERCEZIONE_VLM.diff`](PIANO_PERCEZIONE_VLM.diff): copre i passi 1–6 della sezione 5, compila, passa 24 test ed è stato provato a ciclo chiuso nella casa e in ldc25. Si applica pulito al submodule:

```bash
cd ~/workspace
git -C tools/agenticros apply --check "$PWD/docs/PIANO_PERCEZIONE_VLM.diff"   # verifica
git -C tools/agenticros apply "$PWD/docs/PIANO_PERCEZIONE_VLM.diff"
```

Il diff è la base; documentazione e configurazione (passi 7–8) vanno scritte a mano.

---

## 0. In breve

| # | Decisione | Perché (dati in sezione 3) |
|---|---|---|
| 1 | Nuova modalità `NEBIUS_PERCEPTION=vlm`: nessun YOLO, il modello vision localizza ogni bersaglio. `yolo` resta il default e il comportamento attuale | richiesta: due versioni, con e senza YOLO |
| 2 | Il modello vision restituisce un **bounding box** del bersaglio, senza overlay. Niente colonne, niente griglia | Kimi-K2.6: errore di bearing mediano 0,2°, IoU 0,90. Colonne MiniCPM: 3,9° di mediana, 63% dei bersagli trovati. Griglia: 21–27% di falsi positivi |
| 3 | Modello vision **`moonshotai/Kimi-K2.6`** con thinking disattivato, default in entrambe le modalità. MiniCPM-V resta utilizzabile (profilo "colonne") | l'unico modello su Nebius con box precisi e latenza stabile di ~1 s (DeepSeek-V4.1-Flash è preciso ma ha p90 di 23–29 s) |
| 4 | Coordinate in **frazioni 0–1**, frame **1024×576** JPEG, **output JSON strutturato** (json_schema) | con "0–1000" Kimi mescola le convenzioni (IoU 0,74 → 0,91); 1024 px è il punto ottimo |
| 5 | **Correggere `parseJsonObject`** (bug attuale, vale anche in modalità yolo) | scarta il 9% delle risposte MiniCPM nella casa e 10 avvistamenti su 12 dell'idrante in ldc25 |
| 6 | Guardie contro gli arrivi falsi: coerenza profondità/box, passo massimo 0,5 m a distanza ignota, verifica sul ritaglio degli avvistamenti VLM, `face_target` al primo avvistamento laterale, passo minimo 1 m se il bersaglio è lontano | ognuna corregge un errore visto a ciclo chiuso (sezione 3.6) |
| 7 | YOLO: oggi **YOLOv8n** (gennaio 2023). Aggiornamento consigliato **YOLO26s esportato con `end2end=False`**, senza modifiche al codice | recall nella casa da 36% a 57% a parità di pipeline |

Risultato atteso: la versione senza YOLO trova e localizza l'87% dei bersagli COCO della casa (oggi 57%, e solo il 26% con un box preciso). Trova anche i bersagli non COCO (86%) e l'idrante di ldc25 fino a 9 m (14/14), con la stessa latenza per passo di oggi.

---

## 1. Stato attuale (cosa c'è oggi)

File in `tools/agenticros/packages/agenticros-nebius/src/`:

- `agent.ts` `observe()` (righe 314–370): con `target.cocoClass` lancia in parallelo YOLO a riquadri (`detectCoco`) e il modello vision (`describe`). Se YOLO non trova il bersaglio usa l'avvistamento del VLM. Per i bersagli non COCO usa solo il VLM. La ROI di profondità è `innerBox(bbox)` per YOLO e l'intera banda per il VLM (riga 357).
- `perception.ts`:
  - `toVisionJpeg` (74–96) riduce il frame 1920×1080 a 768×432 e disegna 9 colonne numerate.
  - `describe` (185–252) chiede a MiniCPM-V la colonna del centro e una taglia (`tiny`…`very_large`). Il "box" del VLM è la banda della colonna con y fissa 0,30–0,55 (riga 247); `height_frac` deriva dalla taglia.
  - `verifyCandidate` (134–179) controlla sul ritaglio i rilevamenti YOLO sotto 0,8 e gli attributi (colore).
- `policy.ts` `isGoalReached` (228–240): per `source: "vlm"` richiede anche `height_frac ≥ 0,25`, perché la banda può contenere oggetti più vicini.
- **Bug** in `parseJsonObject` (54–72): prende il testo dalla prima `{` all'ultima `}`. MiniCPM-V spesso chiude il JSON compatto con una graffa in più (`...}}}`) e l'intera risposta viene scartata. Il bersaglio risulta quindi "non visibile" anche quando il modello l'ha visto.

YOLO (`packages/object-detection/src/`): YOLOv8n ONNX (COCO, 80 classi, 12,8 MB fp32) scaricato dal mirror `huggingface.co/Kalray/yolov8` in `~/.agenticros/models/yolov8n.onnx`. Input 640 letterbox, onnxruntime-node su CPU, output `[1, 84, 8400]` decodificato in `detector.ts`. `detectClassTiled` (`tiled.ts`) esegue il frame intero più 5 riquadri 480×480 sull'orizzonte, cioè 6 inferenze (~0,5 s) per ogni classe cercata.

---

## 2. Come è stato valutato

- **Frame reali dalla sim**: 56 nella casa (7 stanze × 8 direzioni) e 17 in ldc25 (idrante a 1,4–9 m, semaforo), con profondità e posa reale di Gazebo.
- **Verità a terra della casa**: proiezione delle mesh visual dei mobili (pose da `house.world`) con z-buffer per oggetto, confrontata pixel per pixel con la profondità della scena. Dà la maschera visibile (le occlusioni sono escluse), il box, la distanza (12° percentile, come l'agente) e il bearing. Verificata a vista. In ldc25 il riferimento è YOLO26s a riquadri (0,88–0,95), verificato a vista.
- **184 query** nella casa (128 con bersaglio visibile, 56 con bersaglio assente; 15 categorie, 6 COCO). Stesse query per ogni configurazione.
- **Metriche**:
  - trovati (TPR) e falsi positivi (FPR);
  - errore di bearing rispetto al centro del box vero;
  - IoU;
  - "distanza ok": distanza misurata con la ROI che userebbe l'agente, entro 0,3 m o il 20% del vero;
  - latenza.
- **Prototipo a ciclo chiuso** (la copia del diff) nella sim headless: 10 corse (sezione 3.6).

Script e risultati sono in [`scripts/vision_eval/`](../scripts/vision_eval/README.md) (i frame grezzi, ~150 MB, non sono in Git e si ricatturano con la sim).

---

## 3. Risultati

Nelle tabelle il grassetto indica il valore migliore di ogni colonna; "in uso" segna la configurazione adottata.

### 3.1 Modelli vision disponibili sulla chiave Nebius

| Modello | Immagini | Box (test sintetico) | Latenza | Note |
|---|---|---|---|---|
| `openbmb/MiniCPM-V-4_5` | sì | y sbagliata | **0,5 s** | attuale; $0,66/$1,11 per M token |
| `moonshotai/Kimi-K2.6` | sì | esatto | 0,7 s | **thinking attivo per default**: disattivarlo con `chat_template_kwargs: {thinking: false}`. `reasoning_effort: "none"` NON funziona su K2.6. $0,95/$4,00 |
| `deepseek-ai/DeepSeek-V4.1-Flash` | sì | esatto | mediana 1,9 s, **p90 23–29 s** | latenza instabile, escluso |
| `moonshotai/Kimi-K3` | sì | esatto | 22 s sotto carico | lento, $3/$15, escluso |
| `Qwen/Qwen3.8-27B` | sì | esatto | 42 s | escluso |
| `zai-org/GLM-5.3-Flash` | sì | esatto | 26–34 s | thinking non disattivabile, escluso |
| `google/gemma-3-27b-it` | sì | approssimativo | 1,4 s | sui frame veri bearing 9,7°, escluso |
| `MiniMaxAI/MiniMax-M3` | sì | sbagliato | 1,3 s | escluso |
| Qwen3.5-397B, GLM-5.2/5.3, tutti i Nemotron | **no** (`does not support image input`) | — | — | — |

Prezzi da un aggregatore terzo (ottobre 2026), da ricontrollare.

### 3.2 Casa: colonne, griglia, box, punto (184 query)

| Configurazione | Trovati | Falsi pos. | Bearing med / p80 | IoU med | Distanza ok | Token in |
|---|---|---|---|---|---|---|
| MiniCPM 9 colonne 768 (produzione, parser attuale) | 52% | 4% | 3,9° / 7,3° | — | 70% | **~400** |
| MiniCPM 9 colonne 768 + parser robusto | 63% | 7% | 3,9° / 7,1° | — | 69% | **~400** |
| MiniCPM 9 colonne 1344 + parser robusto | 65% | 5% | 4,2° / 8,2° | — | 70% | ~660 |
| MiniCPM griglia 9×5 (768 / 1344) | 71% | 27% / 21% | 3,9–5,2° / 13° | 0,13–0,19 | 43–51% | — |
| MiniCPM bbox 0–1000 (768 / 1344) | 80–82% | 12–14% | 5,0° / 11–12° | 0,13 | 55–60% | — |
| MiniCPM punto 1344 | 79% | 11% | 5,7° / 12,5° | punto sull'oggetto 26% | 46% | — |
| Gemma-3-27B bbox 1280 | 77% | 5% | 9,7° / 21° | 0,11 | 53% | — |
| DeepSeek-V4.1-Flash bbox 1280 | 70% | 4% | 0,3° / 1,0° | 0,81 | 89% | ~840 |
| Kimi-K2.6 bbox 0–1000 1280 | 85% | **2%** | 0,2° / 1,2° | 0,74 | 72% | ~1400 |
| Kimi-K2.6 bbox pixel 1280 | 84% | 5% | 6,9° / 45° | 0,13 | 53% | — |
| Kimi-K2.6 bbox frazioni 768 | 80% | **2%** | 0,2° / 0,9° | 0,91 | 84% | ~675 |
| Kimi-K2.6 bbox frazioni 1024 | 85% | **2%** | 0,2° / 0,7° | 0,91 | **90%** | ~1000 |
| Kimi-K2.6 bbox frazioni 1280 | 82% | 5% | 0,2° / 0,8° | 0,91 | 86% | ~1420 |
| Kimi-K2.6 bbox frazioni 1920 | 80% | 11% | **0,1° / 0,5°** | **0,93** | 86% | ~2900 |
| Kimi-K2.6 prompt finale 1024 (json_schema + porte) — **in uso** | **86%** | 4% | 0,2° / 0,9° | 0,90 | 88% | ~1060 |

Conclusioni:

- **Le colonne sono valide solo per MiniCPM**, che non sa dare coordinate. Sono la sua modalità migliore (meno falsi positivi, bearing migliore), ma restano grossolane: ±9° al centro, banda di profondità che include oggetti più vicini.
- **La griglia è peggio delle colonne** (falsi positivi 21–27%, distanza ok 43–51%) ed è più complicata. Scartata.
- **Una risoluzione più alta non aiuta MiniCPM**: 768 e 1344 danno gli stessi risultati, il limite è il modello.
- Con un modello che sa localizzare, il box diretto rende inutili overlay e colonne. **Kimi-K2.6 in frazioni a 1024 px** è il punto ottimo:
  - a 768 px costa meno token e perde un po' di bersagli;
  - a 1920 px aumentano i falsi positivi.
- I falsi negativi di Kimi sono quasi tutti casi ambigui o minuscoli:
  - la "TV" del mondo è renderizzata come una foto di gruppo a parete;
  - il divano visto a 0,4 m è solo tessuto;
  - la scarpiera viene descritta come "scaffale a pioli";
  - il resto sono oggetti sotto i 200 px.

### 3.3 Latenza misurata in sequenza (20 chiamate, frame reali)

| Configurazione | Mediana | p90 | JSON validi |
|---|---|---|---|
| MiniCPM colonne 768 (attuale) | **0,96 s** | **1,05 s** | 17/20 |
| Kimi-K2.6 frazioni 1024 | 1,00 s | 1,20 s | **20/20** |
| Kimi-K2.6 frazioni 1024 + json_schema | 0,99 s | 1,16 s | **20/20** |

A ciclo chiuso, senza YOLO: percezione 1,7–1,9 s per passo (vision 1,2–1,3 s), cioè come oggi con YOLO e vision in parallelo. Costo stimato con Kimi: ~$0,0015 per chiamata, $0,02–0,08 per compito.

### 3.4 ldc25: idrante (1,4–9 m) e semaforo, 14 positivi e 12 negativi

| Configurazione | Trovati | Falsi pos. | Errore di bearing max | Errore di distanza max |
|---|---|---|---|---|
| MiniCPM colonne 768 (produzione) | 2/14 | **0** | 5,4° | 0,57 m |
| Kimi-K2.6 frazioni 768 / 1280 / 1920 | **14/14** | **0** | **0,4°** | **0,03 m** |

MiniCPM l'idrante lo vedeva in 12 frame su 12: 10 risposte erano JSON con una `}` in più, scartate dal parser.

### 3.5 Confronto finale sui 68 bersagli COCO della casa (stesse query)

| Pipeline | Trovati e localizzati |
|---|---|
| Attuale: YOLOv8n, poi MiniCPM colonne, parser attuale | 57% (solo il 26% con box YOLO) |
| Attuale con parser corretto | 69% |
| YOLO26s + MiniCPM con parser corretto | 74% |
| YOLO26s + Kimi-K2.6 | **88%** |
| Solo Kimi-K2.6 (modalità vlm) | 87%, sempre con box preciso |

### 3.6 Prove a ciclo chiuso del prototipo (sim headless, posa reale usata solo per verificare)

| # | Mondo / richiesta | Esito | Cosa ha insegnato |
|---|---|---|---|
| 1 | casa, "vai vicino al frigorifero" | ❌ falso successo a 0,91 m da una **sedia**; frigo a 3,9 m | il box del frigo conteneva lo schienale di una sedia più vicina e la profondità misurava la sedia → **verifica di coerenza profondità/box** |
| 2 | idem, con controllo "distanza vs metri percorsi" | "percorso bloccato" (tavolo e sedie in mezzo) | onesto |
| 3 | "vai vicino al cestino", stesso controllo | ❌ dopo una lettura sbagliata le letture giuste sono state scartate e il robot ha fatto 1 m alla cieca sul cestino | **non usare il controllo sui metri percorsi**; limitare a 0,5 m il passo quando la distanza è ignota (il corridoio frontale non vede ostacoli più bassi della camera) |
| 4 | cestino, guardie finali | ✅ 5 passi, 0,73 m misurati (vero ~0,72) | |
| 5 | frigorifero, guardie finali | ✅ 11 passi, ~67 s, 0,89 m (vero 0,87) | |
| 6 | ldc25, "cerca l'idrante rosso e vacci vicino" (vlm) | ✅ 10 passi, 0,93 m (vero ~0,92) | |
| 7 | ldc25, stessa richiesta in modalità **yolo** con Kimi | ✅ 15 passi, `[Verify]` di Kimi sul colore ok | Nemotron copia "0,5 m" dallo storico → **passo minimo 1 m se il bersaglio è lontano** |
| 8 | frigorifero con regola `face_target` | ✅ 11 passi, senza deviazione iniziale | nelle 5 corse precedenti Nemotron usava sempre `search` per "girarsi verso" un bersaglio appena visto, superandolo |
| 9 | "vai vicino all'armadio" | ❌ falso successo davanti alla **porta a soffietto** (scambiata per armadio in 2 frame) | la conferma su due frame non ferma un errore coerente → **verifica sul ritaglio** |
| 10 | idem con verifica sul ritaglio | ✅ respinti 5 falsi (porte ×2, condizionatore ×2, varco antitaccheggio); armadio vero raggiunto a 0,81 m (vero 0,81) | |

Altre prove offline sulle guardie:

- **verifica geometrica profondità/box**: entro 1,5 m intercetta 17 delle 20 letture "troppo vicine" (occlusore), con 0 falsi allarmi su 88 letture corrette;
- **campo `occluded` chiesto a Kimi**: utile solo come informazione, non per decidere (recall 45%, falsi allarmi 6%);
- **statistiche alternative di profondità sulla ROI**: il "cluster più vicino con almeno il 25% dei pixel" migliora poco sul 12° percentile attuale (91% contro 88% di distanze ok) e nessuna delle due risolve l'occlusione forte (lo schienale copriva metà del box): non vale la modifica al tool MCP.

---

## 4. Design scelto, con motivazione

### 4.1 Due modalità, scelte dall'ambiente

- `NEBIUS_PERCEPTION=yolo` (default): come oggi. YOLO per i bersagli COCO, VLM per gli altri e come ripiego; verifica sul ritaglio dei rilevamenti YOLO sotto 0,8 e degli attributi.
- `NEBIUS_PERCEPTION=vlm`: `detectCoco` non viene mai chiamato, quindi onnxruntime non viene caricato e il modello YOLO non viene scaricato. `coco_class` di Nemotron viene ignorato.

### 4.2 Profili per modello vision (`vision.ts`, nuovo)

Il comportamento dipende dal modello, non da flag sparsi:

```ts
"moonshotai/Kimi-K2.6":  { grounding: "box",     width: 1024, extraBody: { chat_template_kwargs: { thinking: false } }, structuredOutput: true }
"openbmb/MiniCPM-V-4_5": { grounding: "columns", width: 768,  extraBody: {},                                          structuredOutput: false }
// modello sconosciuto: "columns", 768 (prudente); override con NEBIUS_VISION_GROUNDING=box|columns
```

`NEBIUS_VISION_MODEL` diventa per default `moonshotai/Kimi-K2.6` in entrambe le modalità. In modalità yolo migliora sia il ripiego sia la verifica sul ritaglio. Con `vlm` e un profilo "columns" l'agente funziona, ma stampa un avviso (±9°).

### 4.3 Richiesta al modello (profilo "box")

- Frame ridotto a 1024×576, JPEG q80, **nessun overlay**.
- Prompt (testato, vedi `describeBox` nel diff): bersaglio con attributi (`"red fire hydrant" (it must be: red)`), "not a similar one (a sofa is not a bed, a cabinet is not a refrigerator)", "if several are visible, give the nearest one", coordinate come **frazioni** con esempio `[0.12, 0.40, 0.25, 0.61]`.
- Risposta `{summary, target: {visible, bbox|null}, doorways: [[x1,y1,x2,y2], ...]}`, imposta con `response_format: {type: "json_schema", strict: true}` (supportato da Nebius per Kimi e MiniCPM).
- `normalizeBox` accetta frazioni e, per difesa, 0–1000. Ordina gli angoli, limita a [0,1] e scarta box degeneri.
- Bearing dal centro x del box (`bearingFromImageX`, invariato), `height_frac` = altezza del box, porte → bearing del centro (filtro "max 3 per frame" invariato).
- Chiamata con timeout di 20 s e 1 retry (`ask()` centralizza modello, `extraBody` del profilo e json_schema). Anche `verifyCandidate` passa da `ask()`: con Kimi il thinking va spento anche lì.

### 4.4 `localization` al posto di `source` per le regole geometriche

`TargetObservation.localization?: "box" | "column"` (assente = "box"):

- ROI di profondità: `innerBox(bbox)` per "box" (YOLO e Kimi), banda intera per "column";
- `isGoalReached`: il requisito `height_frac ≥ 0,25` vale solo per "column". Un box stretto è affidabile come quello di YOLO; un cestino a 1 m ha `height_frac` ~0,22.
- `source` resta per la logica di fiducia: i soli rilevamenti YOLO ≥ 0,8 sono confermati subito, gli altri richiedono due frame consecutivi (invariato).

### 4.5 Guardie contro gli arrivi falsi (entrambe le modalità)

1. **Coerenza profondità/box** (`depthConsistentWithBox` in `policy.ts`, chiamata in `observe()` dopo la lettura di profondità): per un oggetto appoggiato a terra a profondità `d`, il bordo inferiore del box deve stare circa alla riga `floorImageY(d) = 0,5 + 0,5·(h_cam/d)/tan(VFOV/2)`, limitata a 1.
   - Se il box finisce sotto l'orizzonte (`y_max > 0,52`) ma più di 0,08 sopra quella riga, la profondità appartiene a qualcosa davanti al bersaglio. In quel caso `occluded = true` e `distance_m = null`.
   - Gli oggetti sopra l'orizzonte (TV a parete, oggetti su un tavolo) non vengono giudicati.
   - `h_cam` = `NEBIUS_CAMERA_HEIGHT_M`, default 0,385 m (base a 0,22 m + ZED a 0,165 m).
2. **Passo limitato se la distanza è ignota**: `maxSafeAdvance` usa `unknownTargetAdvanceM = 0,5` quando il bersaglio è visibile ma senza distanza (profondità fallita, occlusore, oggetto lontano oltre la portata di 10 m).
   - Il corridoio frontale (`FRONT_ROI`, y 0,25–0,5) non vede ostacoli più bassi della camera: senza questo limite il robot ha fatto 1 m sul cestino.
   - La nota "advance limited to 0.5 m: target distance unknown" entra nello storico, così Nemotron non la scambia per una preferenza.
3. **Verifica sul ritaglio degli avvistamenti VLM** (`checkVisionSighting` in `agent.ts`): quando un avvistamento `source: "vlm"` verrebbe confermato (secondo frame di fila) e quando varrebbe come arrivo, `verifyCandidate(..., force=true)` lo ricontrolla sul ritaglio ingrandito.
   - Se non corrisponde, l'avvistamento diventa "non visibile".
   - Costo: 1–2 chiamate in più per compito.
   - Le verifiche forzate non impostano `verifiedOnce`, che resta riservato ai candidati YOLO.
4. **Primo avvistamento laterale → `face_target`**: in `planIntent` `search` viene rifiutato se il bersaglio è visibile, non confermato, al primo frame (`sightingStreak === 1`) e oltre `alignToleranceDeg`; il motivo suggerisce `face_target`. Quando il bersaglio è già davanti, `search` resta permesso (il caso "divano preso per letto" del test esistente).
5. **Passo minimo 1 m se il bersaglio è lontano** (distanza − stop ≥ 1,5 m), 0,5 m altrimenti: Nemotron copia i passi corti dallo storico.

Da **non** introdurre (provati e scartati):

- il controllo "distanza attuale vs distanza precedente meno metri percorsi": un riferimento sbagliato fa scartare le letture giuste;
- il flag `occluded` chiesto al VLM come criterio di decisione.

### 4.6 Errori del modello vision

- In modalità `vlm`, se `describe()` fallisce `observe()` restituisce `null`: nessuna decisione e nessun movimento su un'osservazione mancante.
- Dopo 3 fallimenti consecutivi il compito termina con "Modello di visione non disponibile" (il robot è comunque fermo; `ros2_estop` all'uscita, invariato).
- Prima un errore del VLM su un bersaglio non COCO interrompeva l'intera esecuzione.
- In modalità yolo l'errore del VLM continua a non bloccare (come oggi).

### 4.7 Parser JSON robusto (`parseJsonObject` in `vision.ts`, riesportato da `perception.ts`)

- Scansione a graffe bilanciate che rispetta stringhe ed escape, con rimozione di `<think>…</think>` e dei fence.
- Restituisce il primo oggetto completo valido.
- Usato da `describe`, `verifyCandidate` e `parseGoal` (Nemotron).

### 4.8 Cosa non cambia

Nemotron e i suoi tool, i tool MCP e i limiti di sicurezza (`ros2_move_for`, `ros2_estop`, clamp di velocità), l'esplorazione e Nav2, `ros2_depth_distance` (12° percentile), il formato dei log su stderr e la risposta in italiano su stdout.

---

## 5. Implementazione passo per passo

Contesto: tutto nel container (`docker exec -it devcontainer-hackathon-nvidia-x86-cudev-1 zsh`), da `~/workspace`. Il codice è nel submodule `tools/agenticros`. Codice e commenti in inglese, documentazione in italiano. `.env` non va mai letto né stampato.

1. **Base**: applicare il diff (vedi inizio documento) e rileggerlo file per file. È il riferimento dei passi 2–6, ma va rivisto, non accettato a scatola chiusa.
2. **`src/vision.ts` (nuovo)**: `Grounding`, `VisionProfile`, `visionProfile(model, override?)`, `parseJsonObject` robusto, `normalizeBox`, `boxReplySchema(withTarget)`. Funzioni pure, senza rete né `sharp`.
3. **`src/perception.ts`**:
   - `PerceptionOptions` acquista `vision: VisionProfile`;
   - `toVisionJpeg(image, width, columns)`;
   - `ask()` privato (timeout 20 s, 1 retry, `extraBody`, json_schema);
   - `describe()` smista fra `describeBox` (nuovo) e `describeColumns` (il vecchio `describe`, con il testo del bersaglio comprensivo di attributi);
   - `localization` impostato su tutti gli avvistamenti;
   - `verifyCandidate(..., force = false)` passa da `ask()`, il log mostra la sorgente e `verifiedOnce` non viene impostato se `force`.
4. **`src/policy.ts`**: `TargetObservation.localization` e `occluded`; `CameraGeometry`, `floorImageY`, `depthConsistentWithBox`; `unknownTargetAdvanceM: 0.5` in `PolicyLimits` e `DEFAULT_LIMITS`; `maxSafeAdvance`; `isGoalReached` su `localization`; regola `face_target` in `planIntent("search")`; passo minimo e nota in `planIntent("approach_target")`.
5. **`src/agent.ts`**:
   - `AgentConfig.perception` e `camera`;
   - `observe()`: `useYolo` dipende dalla modalità, il fallimento del VLM restituisce `null` in modalità vlm, ROI su `localization`, guardia geometrica dopo la profondità;
   - `lastImage`;
   - `checkVisionSighting()` chiamato in `approach()` **prima** di `recordObservation`;
   - gestione dei fallimenti (`MAX_PERCEPTION_FAILURES = 3`);
   - `summarizeObservation` con `column` e `occluded`;
   - aggiornare il commento in testa a `observe()` e il log "YOLO missed … using the vision-model sighting".
6. **`src/index.ts`**:
   - `envChoice()`;
   - `NEBIUS_PERCEPTION` (`yolo|vlm`, default `yolo`);
   - `NEBIUS_VISION_GROUNDING` (`box|columns`, opzionale);
   - `NEBIUS_CAMERA_HEIGHT_M` (default 0,385);
   - `DEFAULT_VISION_MODEL = "moonshotai/Kimi-K2.6"`;
   - riga di avvio `[Perception] mode=… vision=… grounding=… width=…`;
   - HFOV letto una volta.
7. **Test** (`src/__tests__/`):
   - `vision.test.ts` (nuovo): parser con `}}}`, `<think>`, fence, prosa con graffe; `normalizeBox` con frazioni, 0–1000, angoli invertiti e casi degeneri; profili;
   - `policy.test.ts`: il test esistente sulla banda VLM ora usa `localization: "column"`; nuovi test per box VLM e arrivo, `depthConsistentWithBox` (frigo dietro la sedia, tavolo a 0,34 m, TV a parete, divano che tocca il bordo), passo con distanza ignota, `face_target` al primo avvistamento laterale, passo minimo da lontano;
   - il test "approach steps are not crawled" va aggiornato: a 4 m il passo è 1 m, a 2,2 m è 0,5 m. Nel diff è già fatto.
8. **Configurazione e documentazione** (non nel diff):
   - `.env.example`: `NEBIUS_VISION_MODEL=moonshotai/Kimi-K2.6`, poi commenti per `NEBIUS_PERCEPTION=yolo  # "vlm" = senza YOLO, il modello vision localizza i bersagli`, `NEBIUS_VISION_GROUNDING`, `NEBIUS_CAMERA_HEIGHT_M=0.385`.
   - `scripts/run_nebius_agent.sh`: nessuna modifica funzionale (le variabili di `.env` e del chiamante passano già); al massimo un commento con l'esempio `NEBIUS_PERCEPTION=vlm ./scripts/run_nebius_agent.sh "…"`.
   - `src/README.md`:
     - schema e passo 2 del "Come funziona";
     - tabella `.env` con `NEBIUS_PERCEPTION`, `NEBIUS_VISION_MODEL` (nuovo default) e `NEBIUS_CAMERA_HEIGHT_M`;
     - il paragrafo sui bersagli più affidabili, che in vlm valgono anche per i non COCO;
     - "Primo avvio lento": vale solo in modalità yolo.
   - `docs/NEBIUS_AGENTICROS.md`:
     - sezione "Percezione" riscritta: due modalità, profili, box in frazioni, guardie;
     - un riassunto delle misure della sezione 3 di questo piano;
     - la riga "nei test i box in pixel … erano inaffidabili, la colonna no" va corretta: vero per MiniCPM, non per Kimi-K2.6;
     - "Latenza".
   - `tools/agenticros/CLAUDE.md`: righe di `perception.ts` e del nuovo `vision.ts` nella tabella dell'adapter.
   - `CLAUDE.md` (repo): riga 4–5 ("MiniCPM-V descrive la scena, YOLO locale…") → modello vision e due modalità.
   - **Dire all'utente** di aggiornare a mano `NEBIUS_VISION_MODEL` nel suo `.env` se lì c'è ancora MiniCPM (l'agente non deve leggere `.env`).
9. **Build e test**:
   ```bash
   bash -ic 'cd ~/workspace/tools/agenticros && pnpm --filter @agenticros/nebius build && pnpm --filter @agenticros/nebius test'
   ```
   Atteso: tutti i test verdi (24 col diff). Nessun altro package cambia, quindi `cbuild` non serve.
10. **Validazione in simulazione** (sezione 6).
11. **Commit** solo se l'utente lo chiede: prima nel submodule (branch `main`, remote `ErLex20/agenticros`), poi il puntatore nel repo padre.

---

## 6. Protocollo di validazione in simulazione

Headless, un compito per volta, robot riportato allo spawn tra un compito e l'altro. Per verificare l'arrivo si usa la posa reale (`ros2 topic echo --once /gz/dottorcane/pose`) con le coordinate degli oggetti di `house.world`. Serve solo a chi verifica e non va mai passata all'agente.

```bash
# terminale 1 (container): sim
ros2 launch go2_sim_worlds go2_sim.launch.py world:=house gui:=false
# riportare il robot allo spawn tra un compito e l'altro
gz service -s /world/default/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean --timeout 3000 \
  --req 'name: "dottorcane", position: {x: 0.0, y: 1.5, z: 0.30}, orientation: {x: 0, y: 0, z: 0, w: 1}'
# terminale 2
NEBIUS_PERCEPTION=vlm ./scripts/run_nebius_agent.sh "vai vicino al frigorifero"
```

| Prova | Atteso |
|---|---|
| casa, vlm, "vai vicino al frigorifero" | successo in ~11 passi (~70 s), ~0,9 m dal frigo. Accettabile anche "percorso bloccato" se il passo devia verso tavolo e sedie; **mai** successo davanti a una sedia |
| casa, vlm, "vai vicino al cestino della spazzatura" | successo in ~5 passi, ~0,7 m |
| casa, vlm, "vai vicino all'armadio" | righe `[Verify] … no match` sulle porte a soffietto; nessun successo davanti alla porta. Può richiedere esplorazione (fino a ~45 passi) |
| casa, vlm, "Guarda davanti al robot e descrivi gli ostacoli. Non muovere il robot." | descrizione in italiano, nessun movimento |
| ldc25, vlm, "cerca l'idrante rosso e vacci vicino" | successo in ~10 passi, ~0,9 m |
| ldc25, **yolo**, stessa richiesta | successo; `[Verify] red fire hydrant (yolo …): match` prodotto da Kimi |
| avvio | `[Perception] mode=vlm vision=moonshotai/Kimi-K2.6 grounding=box width=1024`; in modalità vlm nessun `[AgenticROS] follow-me: downloading YOLOv8n` |

Insidie del container:

- prima di rilanciare la sim chiudere i processi orfani (`pkill -9 -f "[g]z sim"` ecc.);
- non mettere nella stessa riga di comando il testo in chiaro dei processi da uccidere (es. `grep "gz sim"` dopo `pkill -f "[g]z sim"`), perché `pkill` uccide la shell stessa;
- l'agente gira da `dist/`: ricompilare dopo ogni modifica.

---

## 7. YOLO: versione attuale e aggiornamento consigliato

**Attuale**: YOLOv8n Ultralytics (10 gennaio 2023), COCO 37,3 mAP, 3,2 M parametri, 80,4 ms CPU ONNX secondo Ultralytics. Licenza AGPL-3.0, come tutti gli YOLO Ultralytics.

Confronto su questi 56 frame della casa, con la stessa pipeline a riquadri del progetto (soglia 0,35, CPU, sim attiva):

| Modello | COCO mAP (Ultralytics) | Recall casa | Falsi pos. | s/frame a riquadri | Note |
|---|---|---|---|---|---|
| YOLOv8n (attuale) | 37,3 | 36% | **26** | 0,47 | frigo 1/16, divano 0/20, TV 0/21 |
| YOLO11n | 39,5 | 37% | **26** | 0,46 | |
| YOLO11s | 47,0 | 44% | 29 | 1,06 | |
| YOLO26n | 40,9 | 39% | 28 | **0,43** | |
| YOLO26s | 48,6 | **57%** | 33 | 0,99 | **consigliato** |
| YOLO26m | **53,1** | 53% | 34 | 2,76 | più lento, non meglio qui |
| YOLOE-26s/m (open-vocabulary, 18 classi della casa) | — | 38–43% su 15 categorie | 69–95 | 1,2–3,1 | armadio 0/5, bilanciere 0/11: non conviene |

**Raccomandazione per la versione con YOLO**: YOLO26s (Ultralytics, gennaio 2026, NMS-free; in CPU ONNX la versione n è fino al 43% più veloce di YOLO11n).

- **Va esportato con `end2end=False`**. Con Ultralytics 8.4.41 l'export di default di YOLO26 produce `[1, 300, 6]` (end-to-end), che `detector.ts` rifiuta ("Unexpected YOLOv8 output shape").
- Con `end2end=False` l'output è `[1, 84, 8400]` come YOLOv8 e YOLO11: decoder e NMS attuali funzionano senza modifiche. È verificato.
- La testa one-to-many è anche leggermente più accurata (40,9 contro 40,1 mAP nella n).

Ultralytics è già installato nel container (`/opt/dua-venv`):

```bash
mkdir -p /tmp/yolo26 && cd /tmp/yolo26
python3 -c "from ultralytics import YOLO; YOLO('yolo26s.pt').export(format='onnx', imgsz=640, end2end=False)"
cp yolo26s.onnx ~/.agenticros/models/yolo26s.onnx
# uso (nessuna modifica al codice):
AGENTICROS_YOLOV8_MODEL=~/.agenticros/models/yolo26s.onnx ./scripts/run_nebius_agent.sh "vai vicino al frigorifero"
```

Opzionale:

- rendere il modello configurabile in modo esplicito (es. `AGENTICROS_YOLO_MODEL` con `AGENTICROS_YOLOV8_MODEL` come alias) e aggiornare il messaggio "downloading YOLOv8n";
- lasciare invariato il download automatico di `yolov8n.onnx` come ripiego;
- il costo è ~1 s per chiamata a riquadri invece di 0,5 s, sopportabile perché gira in parallelo alla chiamata vision (~1 s).

Alternative non provate qui:

- **RF-DETR** (Roboflow, Apache-2.0, N 48,4 / S 53,0 AP COCO): da considerare se la licenza AGPL è un problema. Ha un output DETR diverso e servirebbe un decoder nuovo.
- **DEIMv2 / D-FINE** (Apache-2.0): stessa considerazione.

Su questi mobili renderizzati, comunque, nessun detector COCO si avvicina al modello vision (sezione 3.5).

---

## 8. Limiti noti e lavoro futuro

- **Aggiramento degli ostacoli**: senza Nav2 il robot non aggira tavolo e sedie davanti al bersaglio. Le guardie trasformano il falso successo in "percorso bloccato", ma non risolvono il problema. Con `nav:=map` la stanza nota si raggiunge prima con Nav2. Idea futura: in caso di `occluded`, mandare a Nav2 un goal nel frame `base_link` lungo il bearing del bersaglio.
- **Vetro**: il sensore di profondità simulato vede attraverso i pannelli di vetro ma non attraverso i telai. Le porte "riportate" dal VLM su vetrate non si possono scartare con la profondità (provato).
- **Ostacoli bassi**: `FRONT_ROI` (y 0,25–0,5) non vede ostacoli più bassi della camera. Il limite di 0,5 m a distanza ignota attenua il problema; una soluzione vera è una ROI sul pavimento o lo scan ostacoli di Nav2.
- **Errori semantici coerenti** (porta presa per armadio): sono mitigati dalla verifica sul ritaglio, non eliminati.
- **Dipendenza da un modello esterno grande**: Kimi-K2.6 su Nebius. In caso di indisponibilità basta `NEBIUS_VISION_MODEL=openbmb/MiniCPM-V-4_5`, con profilo colonne e parser corretto. Un ripiego automatico (`NEBIUS_VISION_FALLBACK_MODEL`) è un'estensione possibile, non necessaria ora.
- **Non determinismo**: anche a temperatura 0 Kimi può cambiare risposta con un prompt diverso (stesso frame dell'armadio: "visibile" con un testo, "non visibile" con un altro). Conferma su due frame e verifica sul ritaglio servono a questo.
