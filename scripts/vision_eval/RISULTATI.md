# Risultati principali della valutazione

I file grezzi (`results/`, `data/`, log) restano solo in locale e non sono in Git; si rigenerano con gli script (vedi [README.md](README.md)). Confronto prima/dopo: [docs/CONFRONTO_PERCEZIONE.md](../../docs/CONFRONTO_PERCEZIONE.md).

## Modelli vision, casa (184 domande: 128 bersagli visibili, 56 assenti)

| Configurazione | Trovati | Falsi pos. | Direzione (mediana) | IoU | Distanza ok |
|---|---|---|---|---|---|
| MiniCPM-V, 9 colonne, 768 px (prima) | 52% | 4% | 3,9° | — | 70% |
| MiniCPM-V, 9 colonne + parser corretto | 63% | 7% | 3,9° | — | 69% |
| MiniCPM-V, griglia 9×5 | 71% | 21–27% | 3,9–5,2° | 0,13–0,19 | 43–51% |
| MiniCPM-V, bbox | 80–82% | 12–14% | 5,0° | 0,13 | 55–60% |
| Gemma-3-27B, bbox | 77% | 5% | 9,7° | 0,11 | 53% |
| DeepSeek-V4.1-Flash, bbox (p90 latenza 23–29 s) | 70% | 4% | 0,3° | 0,81 | 89% |
| Kimi-K2.6, bbox 0–1000 | 85% | **2%** | **0,2°** | 0,74 | 72% |
| Kimi-K2.6, bbox in frazioni, 1024 px | 85% | **2%** | **0,2°** | **0,91** | **90%** |
| Kimi-K2.6, prompt finale (json_schema + porte), 1024 px — **in uso** | **86%** | 4% | **0,2°** | 0,90 | 88% |

Il grassetto indica il migliore di ogni colonna. Latenza in sequenza: MiniCPM 0,96 s, Kimi-K2.6 a 1024 px 0,99 s.

## ldc25 (idrante 1,4–9 m e semaforo, 14 positivi)

MiniCPM-V a colonne 2/14 (10 risposte scartate dal vecchio parser); Kimi-K2.6 14/14, errore di direzione massimo 0,4°, distanza entro 3 cm.

## YOLO a riquadri sui mobili COCO della casa (soglia 0,35)

| Modello | Recall | Tempo per frame (CPU) |
|---|---|---|
| YOLOv8n (attuale) | 36% | 0,47 s |
| YOLO11n / YOLO11s | 37% / 44% | 0,46 / 1,06 s |
| YOLO26n / YOLO26s (consigliato) / YOLO26m | 39% / **57%** / 53% | **0,43** / 0,99 / 2,76 s |
| YOLOE-26s / 26m (15 categorie, anche non COCO) | 38% / 43% | 1,17 / 3,11 s |

## Corse a ciclo chiuso (versione finale)

| Richiesta | Esito |
|---|---|
| casa, "vai vicino al frigorifero" (senza YOLO) | arrivato in 11 passi, 0,89 m (vero 0,87) |
| casa, "vai vicino al cestino della spazzatura" | arrivato in 5 passi, 0,73 m |
| casa, "vai vicino all'armadio" | 5 falsi avvistamenti respinti, armadio raggiunto a 0,81 m |
| ldc25, "cerca l'idrante rosso e vacci vicino" (senza YOLO / con YOLO) | arrivato in 10 / 15 passi |

## Esplorazione senza mappa: grafo dei luoghi (ottobre 2026)

Contesto, metodo e conclusioni: [docs/ESPLORAZIONE_GRAFO.md](../../docs/ESPLORAZIONE_GRAFO.md). Verità a terra della topologia: [`house_topology.json`](house_topology.json) (zone, passaggi, vetrate, finestre), proiettata nei 56 frame con la posa reale e la mappa.

### Aperture riportate dal modello vision (Kimi-K2.6, 184 risposte)

| Prompt (`eval_vlm.py`) | "Aperte" su un passaggio vero | Vetrate chiuse dichiarate aperte | Passaggi riportati (entro 6 m, ≥ 10°) | Bersagli trovati | Latenza mediana |
|---|---|---|---|---|---|
| `final` (in uso: lista di porte) | 48% (63/132) | 42 | 27% (19/70) | 86% | 2,49 s* |
| `graph` (tipo, "cosa c'è oltre", zona, anche finestre) | 64% (49/77) | 9 | 31% (22/70) | 84% | 3,54 s |
| `exits` (tipo: aperta, vetro, chiusa) | 64% (70/109) | 11 | 31% (22/70) | 83% | 2,74 s* |

\* misurate in sequenza nello stesso momento, alternando i due prompt sulle stesse 20 domande (`final` valeva 1,25 s nella misura di giorni prima: è cambiato il carico di Nebius, non il prompt). Bersagli trovati: 6 domande trovate solo da `final`, 2 solo da `exits` (non significativo, p ≈ 0,3).

### Zona e "cosa c'è oltre" (prompt `graph`)

| Punto di cattura | Zona indicata (numero di risposte, 8 viste per punto) |
|---|---|
| camera da letto | living room 11, bedroom 10, office 5, hallway 4 |
| seconda stanza | hallway 7, other 4, living room 4 |
| soggiorno | living room 13, bedroom 5, office 3 |
| cucina | kitchen 12, living room 9, dining room 5 |

Il varco verso la camera visto dal centro: "cosa c'è oltre" non nomina mai camera o letto (0/9: "adjacent room with chandelier", "area beyond divider").

### Dove esplorare dopo un giro senza bersaglio (`explore_choice_eval.py`, 65 casi)

7 punti di cattura × bersagli che stanno solo in altre zone; 4 viste a ~90°. "Progresso" = di quanto si accorcia il percorso a piedi (distanza geodetica sulla mappa, ostacoli gonfiati di 0,2 m) verso la zona del bersaglio dopo una camminata di 2,5 m nella direzione scelta, fermandosi a 0,45 m dagli ostacoli (vetrate comprese).

| Scelta | Camminate che avvicinano (> 0,5 m) | che allontanano (> 0,5 m) | Progresso medio |
|---|---|---|---|
| **Kimi sul mosaico delle viste, vista + punto** (2 corse) | **58–65%** | **8–12%** | **+0,83…+1,04 m** |
| Kimi, prima elenca le aperture per vista, poi sceglie | 65% | 20% | +0,88 m |
| Nemotron sulle descrizioni delle viste (tool `explore`) | 25% | 22% | −0,14 m |
| Una vista con porta "aperta" (prompt `exits`) | 34% | 29% | −0,07 m |
| Direzione più aperta (regola precedente) | 38% | 42% | −0,16 m |
| Una vista a caso (media) | — | — | −0,25 m |

| Per tipo di bersaglio | Kimi mosaico + punto | Più aperta |
|---|---|---|
| Ala ovest (letto, armadio, comodino, scrivania; 38 casi) | 74–82% avvicinano, +1,06…+1,38 m | 21%, −0,79 m |
| Open space (27 casi) | 37–41%, +0,52…+0,55 m | 63%, +0,73 m |

Dallo spawn (le 4 viste del giro del robot, `spawn_00…03`, 6 ripetizioni): il letto, l'armadio e la scrivania non vengono mai scelti nella direzione giusta (0/6 ciascuno: Kimi sceglie una porta a vetri o la cucina), il frigorifero sempre (6/6). Aggiungere al prompt che le vetrate non si attraversano o di preferire zone non visibili non cambia il risultato (0/4).

### Calibrazione dei movimenti (diagnostica `AGENTICROS_DEBUG_POSE_TOPIC`, house headless, RTF 1,0)

| Efficienze | −90° comandati | −45° | +20° | 1 m | 0,5 m |
|---|---|---|---|---|---|
| 0,65 / 0,7 (prima) | −105,8…−106,7° | −53,4…−53,7° | +24,3…+25,8° | 1,18–1,22 m | 0,59 m |
| **0,77 / 0,84** | −90,8…−93,1° | −45,7° | +18,2° | 0,97 m | 0,51 m |

### A ciclo chiuso: serie A/B (13 ottobre 2026, 16 corse)

Casa headless, `nav:=none`, RTF 1,0; arrivo verificato sulla posa reale. Distanza finale dal centro dell'oggetto: un arrivo vero sul letto è a 2,2–2,4 m (il letto è grande), sul frigo a 1,5–1,7 m (fronte del frigo a ~1,1 m dalla camera).

| Corsa | Modalità | Passi | Esito | Esplorazioni | Distanza finale | Note |
|---|---|---|---|---|---|---|
| letto 1 | vision | 62 | non trovato | 7 | 14,3 m | a est, nella cucina |
| letto 1 | open | 63 | **arrivato** | 7 | 2,37 m | passando dalla seconda stanza |
| letto 2 | vision | 56 | **arrivato** | 6 | 2,65 m | |
| letto 2 | open | 80 | passi esauriti | 4 | 9,5 m | sempre nel soggiorno |
| letto 3 | vision | 63 | falso arrivo | 7 | 7,8 m | divano (guardia aggirata, ora corretta) |
| letto 3 | open | 80 | passi esauriti | 6 | 9,6 m | |
| scrivania 1 | vision | 10 | falso arrivo | 1 | 10,9 m | tavolino, "reception desk" |
| scrivania 1 | open | 68 | non trovata | 7 | 9,9 m | |
| scrivania 2 | vision | 79 | tempo esaurito | 4 | 15,7 m | a sud-est, vicino all'ingresso |
| scrivania 2 | open | 77 | non trovata | 6 | 14,1 m | |
| frigo 1–3 | vision | 19, 13, 25 | 2 **arrivati**, 1 "nessuna azione sicura" | 0 | 1,49 / 9,8 / 1,54 m | fermata davanti al divano (ora: deviazione dall'altro lato) |
| frigo 1–3 | open | 29, 31, 26 | 3 **arrivati** | 0 | 1,47–1,67 m | |

Missioni con esplorazione (letto e scrivania): `vision` 1 su 5, `open` 1 su 5.

Rotazioni comandate di almeno 60° nelle corse con esplorazione (`closed_loop_traj.py --rotations`), frazione girata davvero per distanza del centro del robot dall'ostacolo più vicino della mappa:

| Distanza | Rotazioni | Mediana | Sotto il 70% |
|---|---|---|---|
| < 0,4 m | 85 | 0,40 | 61 |
| 0,4–0,8 m | 56 | 0,97 | 5 |
| 0,8–1,2 m | 87 | 0,97 | 9 (accanto al porta-manubri, assente dalla mappa) |
| > 1,2 m | 102 | 0,97 | 0 |

Deriva della direzione stimata sulle righe `[Explore]`, a fine corsa: oltre 140° in 3 corse su 9. Errore di posizione dei luoghi del grafo (corse `vision`): fino a 3,2 m e fino a 10,1 m.

Prove singole allo spigolo, prima della serie, partendo a 0,5–1,7 m dal varco ovest: 3 arrivi al letto su 4 (2,23–2,40 m). La quarta si è arresa davanti al telaio, con il letto confermato a 3,2 m.

### Dopo la serie A/B: corridoio, verifica sul ritaglio, IMU

**Spazio libero davanti** (`corridor_eval.py`, 63 frame della casa con posa; verità: mappa, vetrate escluse, larghezza del corpo ±0,25 m). Sui 31 frame con un ostacolo entro 2 m dalla camera:

| Misura | Errore mediano | Sovrastime > 0,5 m | Sottostime > 0,5 m |
|---|---|---|---|
| fascia sopra l'orizzonte (x 0,4–0,6, y 0,25–0,5, 12° percentile) | +0,04 m | 5 | 0 |
| minimo fra fascia e corridoio 3D (5 cm–1 m da terra, 25° pixel più vicino) | −0,02 m | 1 | 1 |

**Verifica sul ritaglio** (`verify_eval.py`, Kimi-K2.6, 176 ritagli: 45 del bersaglio, 131 di oggetti simili):

| Prompt | Bersagli confermati | Sosia accettati | letto | divano | scrivania | frigo | armadio |
|---|---|---|---|---|---|---|---|
| prima la risposta | 38/45 | 46/131 | 3/3, divani 6/20 | 16/20, letti 2/3 | 2/3, tavoli 34/49 | 14/14, mobili 2/16 | 3/5, sosia 2/43 |
| prima il nome | 27/45 | 10/131 | 0/3, divani 4/20 | 11/20, letti 0/3 | 2/3, tavoli 4/49 | 12/14, mobili 2/16 | 2/5, sosia 0/43 |
| prima il nome, parti incluse | 35/45 | 19/131 | 3/3, divani 8/20 | 13/20, letti 0/3 | 2/3, tavoli 6/49 | 14/14, mobili 4/16 | 3/5, sosia 1/43 |

**Direzione dall'IMU** (`imu_check.sh`: 8 rotazioni da −90° attraverso il server MCP, ognuna seguita da fotogramma, profondità e corridoio; verità: posa di Gazebo a 1 Hz). Differenza fra IMU e verità a robot fermo: con la coda di default (10 messaggi) da −5° a +27°, oscillante; con la coda di 500 fra −3° e −8° dopo 720°, e in una seconda prova, su una sim appena riavviata, fra −2° e +9° dopo 704° (con un salto di +8° a robot fermo che la posa vera non mostra). Sulla sim nuova −90° comandati diventano −88° veri; sulla sim degradata dopo un incastro (vedi sotto) −57…−68°.

### A ciclo chiuso: seconda serie A/B (13 ottobre 2026, pomeriggio, 10 corse)

Con direzione dall'IMU, corridoio, sblocco delle rotazioni e verifica con il nome prima; sim rilanciata prima della serie. Distanza finale dalla traiettoria registrata.

| Corsa | Modalità | Passi | Esito | Esplorazioni | Distanza finale | Note |
|---|---|---|---|---|---|---|
| letto 1 | vision | 21 | **arrivato** | 1 | 2,39 m | |
| letto 1 | open | 36 | **arrivato** | 3 | 2,28 m | |
| scrivania 1 | vision | 77 | non trovata | 7 | 12,6 m | sempre nel centro; 1 sblocco |
| scrivania 1 | open | 14 | falso arrivo | 1 | 10,7 m | "reception desk" nel soggiorno |
| letto 2 | vision | 29 | **arrivato** | 1 | 2,39 m | |
| letto 2 | open | 36 | **arrivato** | 3 | 2,38 m | |
| scrivania 2 | vision | 69 | tempo esaurito | 4 | 6,8 m | 4 sblocchi |
| scrivania 2 | open | 12 | falso arrivo | 1 | 10,5 m | "reception desk" nel soggiorno |
| letto 3 | vision | 80 | passi esauriti | 6 | 10,0 m | centro ed est |
| letto 3 | open | 37 | **arrivato** | 3 | 2,36 m | |

Missioni con esplorazione: `vision` 2 su 5, `open` 3 su 5 (prima serie: 1 su 5 ciascuna). Letto: 5 su 6 (prima serie 2 su 6).

Rotazioni comandate di almeno 60° (`closed_loop_traj.py --rotations`, 222):

| Distanza dall'ostacolo | Rotazioni | Mediana | Sotto il 70% |
|---|---|---|---|
| < 0,4 m | 15 | 0,87 | 7 |
| 0,4–0,8 m | 63 | 0,97 | 1 |
| 0,8–1,2 m | 46 | 0,98 | 0 |
| > 1,2 m | 98 | 0,98 | 0 |

Errore della direzione stimata a fine corsa: entro ±10° in 8 corse su 10, +25° e +44° nelle altre due (`vision`). Due serie precedenti sono state scartate: una interrotta per il robot incastrato nel porta-manubri, con il recupero precedente (2 marce indietro), e una girata su una sim degradata (rotazioni al 65%, `*_aborted`, `*_degraded` in `results/closed_loop/`).
