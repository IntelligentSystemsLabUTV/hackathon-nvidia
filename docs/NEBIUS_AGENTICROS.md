# Nebius + AgenticROS

AgenticROS è il livello di accesso e sicurezza ROS; Nebius è il livello decisionale. L'adapter `tools/agenticros/packages/agenticros-nebius` esegue un ciclo osservazione → decisione → azione finché l'obiettivo non è raggiunto:

```text
ros2_camera_snapshot ─► Kimi-K2.6 (box) [+ YOLO a riquadri] ─┐
ros2_depth_distance  ─► distanza bersaglio, spazio libero ─┤
                                                     ▼
                         Nemotron: search | face_target | approach_target | finish
                                                     │ validazione del controller
                                                     ▼
                         ros2_move_for (limitato, stop garantito) ── ripeti
```

Il modello non comanda direttamente il robot: sceglie un'intenzione semantica, il controller calcola angoli e distanze, applica distanza di arresto e margine dagli ostacoli, e rifiuta le azioni non valide (il rifiuto torna al modello nel passo successivo). Se Nemotron non restituisce un'azione utilizzabile, interviene una policy deterministica equivalente. La posa reale di Gazebo non viene mai passata al modello.

## Avvio

Primo terminale:

```bash
cd ~/workspace
source install/setup.zsh
ros2 launch ldc25-sim ldc25_dottorcane.launch.py
```

Secondo terminale:

```bash
cd ~/workspace
./scripts/run_nebius_agent.sh "cerca l'idrante rosso e vacci vicino"
# con YOLO per i bersagli COCO (di default solo il modello vision)
NEBIUS_PERCEPTION=yolo ./scripts/run_nebius_agent.sh "cerca l'idrante rosso e vacci vicino"
```

La richiesta viene prima classificata da Nemotron:

| Modalità | Esempio | Comportamento |
|---|---|---|
| `approach` | "cerca l'idrante rosso e vacci vicino" | ricerca ruotando, allineamento, avvicinamento fino alla distanza di arresto |
| `describe` | "descrivi gli ostacoli, non muoverti" | un frame, descrizione in italiano, nessun movimento |
| `move` | "ruota a destra di 90 gradi e avanza di un metro" | movimenti espliciti, avanzamento limitato dallo spazio libero |
| `stop` | "fermati" | `ros2_estop` |
| `goto` | "vai in camera da letto" (solo con `nav:=map`) | Nav2 fino alla stanza, poi descrizione di ciò che vede |

## Percezione

Due modalità, scelte con `NEBIUS_PERCEPTION` (dettagli e misure in [CHANGELOG.md](CHANGELOG.md)):

| `NEBIUS_PERCEPTION` | Chi localizza il bersaglio |
|---|---|
| `vlm` (default) | solo il modello vision: YOLO non viene caricato né scaricato |
| `yolo` | YOLO a riquadri per i bersagli COCO; il modello vision per gli altri e quando YOLO non trova nulla |

- **Modello vision**: default `moonshotai/Kimi-K2.6` (thinking disattivato con `chat_template_kwargs: {thinking: false}`). Riceve il frame ridotto a 1024×576, **senza overlay**, e restituisce in JSON strutturato (`response_format` json_schema) il **bounding box** del bersaglio in frazioni 0–1 dell'immagine, più le porte verso altre stanze. Nella casa: 86% dei bersagli trovati, errore di bearing mediano 0,2°, IoU 0,90 con la verità a terra; l'idrante di ldc25 fino a 9 m 14 volte su 14.

  ![Box di Kimi-K2.6](img/vlm-box-kimi.jpg)

- **Profili per modello** (`vision.ts`): Kimi-K2.6 usa i box; `openbmb/MiniCPM-V-4_5` non sa dare coordinate affidabili (IoU dei box 0,13) e usa ancora il frame con 9 colonne numerate, indicando la colonna del centro (±9°). Un modello sconosciuto usa le colonne, salvo `NEBIUS_VISION_GROUNDING=box`.

  ![Colonne di MiniCPM-V](img/vlm-colonne-minicpm.jpg)

  Qui MiniCPM-V indica la colonna 2 per il frigorifero, che sta nella 3: la colonna è la sua modalità migliore, ma resta grossolana. Una griglia 9×5 è stata provata e scartata (21–27% di falsi positivi).
- **Bersagli COCO in modalità yolo** (idrante, semaforo, stop sign...): YOLOv8n locale di `@agenticros/object-detection`. `detectClassTiled` analizza il frame intero e 5 riquadri lungo l'orizzonte: sul frame 1920×1080 ridotto a 640 px l'idrante a 6 m aveva confidenza < 0,2, sui riquadri 0,7–0,9. Nella casa YOLOv8n trova solo il 36% dei mobili COCO (frigo 1/16, divano 0/20): lì il modello vision fa quasi tutto il lavoro. Si può usare YOLO26s (57%) senza modifiche al codice, vedi il changelog.
- **Attributi** non visibili a YOLO (colore): verificati dal modello vision sul ritaglio del box.
- **Distanza**: `ros2_depth_distance` sulla parte centrale del box (12° percentile) e un corridoio di circa ±12° davanti al robot. Con la banda delle colonne si misura l'intera banda.

  ![ROI colonna e ROI del box](img/roi-colonna-vs-box.jpg)

- **Guardie contro gli arrivi falsi** (entrambe le modalità):
  - se il bordo inferiore del box è molto più in alto di dove si vedrebbe il pavimento alla distanza letta, la profondità appartiene a qualcosa davanti al bersaglio (una sedia davanti al frigo): distanza ignota, niente arrivo;
  - con bersaglio visibile ma distanza ignota il passo è al massimo 0,5 m (il corridoio frontale non vede ostacoli più bassi della camera);
  - un avvistamento del modello vision viene ricontrollato sul ritaglio quando verrebbe confermato e prima dell'arrivo (una porta a soffietto scambiata per armadio);
  - al primo avvistamento laterale il controller chiede `face_target` invece di `search`; da lontano il passo minimo di avvicinamento è 1 m; entro 12° dal centro `face_target` è rifiutato, perché `approach_target` allinea e avanza da solo (un letto a 7,4 m ricentrato due volte di 5° è stato perso al terzo frame);
  - un avvistamento che comincia già alla distanza d'arrivo con il riquadro che riempie l'immagine non viene confermato dalla sola ripetizione (un divano a 0,37 m preso per il letto);
  - **deviazione intorno a un ostacolo** davanti a un bersaglio confermato: se due movimenti di fila lasciano il bersaglio fermo nell'immagine, il robot è bloccato (per esempio contro lo spigolo di una porta a soffietto, con la profondità che vede spazio libero oltre) e gira di 40° dal lato opposto al bersaglio; se invece non c'è spazio per avanzare verso il bersaglio (il telaio della porta a 0,48 m, il letto a 3,2 m oltre), gira di 40° dal lato del bersaglio, e la volta dopo dall'altro. In entrambi i casi avanza fino a 0,7 m e riprende l'avvicinamento; "percorso bloccato" solo dopo 3 deviazioni dallo stesso punto. Dettagli in [ESPLORAZIONE_GRAFO.md](ESPLORAZIONE_GRAFO.md).

  ![Guardia di occlusione](img/guardia-occlusione.jpg)

- **Robustezza**: il JSON del modello vision viene letto con un parser a graffe bilanciate (prima una `}` in più faceva scartare la risposta). In modalità `vlm`, se il modello vision non risponde il robot non si muove; lo stesso se uno snapshot della camera va in timeout (prima chiudeva l'intero compito). Dopo 3 fallimenti consecutivi il compito si interrompe.

## Navigazione con Nav2

All'avvio l'agente chiama `ros2_list_actions` e sceglie la modalità in base a ciò che gira (`go2_sim.launch.py nav:=...`, vedi [GAZEBO_SETUP.md](GAZEBO_SETUP.md)):

| Simulazione | Stanze | "vai in camera da letto" | Bersaglio non visto dopo un giro |
|---|---|---|---|
| `nav:=map` (Nav2 + AMCL) | `ros2_list_places` | `goto bedroom`: Nav2 fino alla stanza, poi descrizione | esplorazione senza mappa (sotto) |
| `nav:=slam` (Nav2 + SLAM) | ignorate: la casa non è nota | `approach bed` | Nav2 verso la frontiera successiva della mappa SLAM, poi nuovo giro |
| `nav:=none` | — | `approach bed` | esplorazione senza mappa: grafo dei luoghi, il modello vision sceglie dove andare |

- **Stanze.** `run_nebius_agent.sh` imposta `AGENTICROS_PLACES_PATH` su `src/go2_sim_worlds/config/places/${GO2_WORLD:-house}.json`. Nemotron riceve nome e descrizione di ogni stanza e sceglie `goto` con `place`, oppure, per un oggetto che sta in una stanza nota ("vai vicino al letto"), `approach` con `place`: prima Nav2 fino alla stanza, poi l'avvicinamento visivo.
- **Navigazione.** `ros2_navigate_to_place` invia `NavigateToPose` tramite la capability `navigate_to`, dichiarata dalla skill locale `config/agenticros-skills/go2-nav2` (`skillPaths` in `config/agenticros.json`). Pianificazione, ostacoli e limiti di velocità sono di Nav2 (parametri allineati ai limiti AgenticROS); l'agente aspetta l'esito (fino a 11 minuti).
- **Frontiere.** Con `nav:=slam` l'intent `explore` diventa l'azione `frontier`: `ros2_action_goal` su `/explore` (`agenticros_explore`, un goal). Se non ci sono frontiere raggiungibili, l'agente torna all'esplorazione senza mappa.
- **Arresto.** `ros2_estop` annulla anche la navigazione: i goal inviati dall'MCP e, con `cancel_goal` a id nullo, tutti i goal di `navigate_to_pose`. Senza, Nav2 tornerebbe a comandare il robot subito dopo il `cmd_vel` nullo. Verificato: `ros2_navigate_to_place` restituisce `canceled` e il robot resta fermo.

Prove (house, headless):

- `nav:=map`, "vai in camera da letto" → `goto bedroom`: Nav2 dalla cucina alla camera in 114 s, poi MiniCPM-V descrive letto, scrivania e sedia.
- `nav:=slam`, mappa vuota, "vai in camera da letto" → `approach bed`: cinque frontiere (~11 minuti, due perse dietro il divano), poi il letto vero è visto da ~5 m e confermato; l'avvicinamento si è fermato a 2,3 m per il limite di 80 passi, perché Nemotron chiedeva passi da 10 cm (ora il minimo è 0,5 m). Ripartito da lì, "vai vicino al letto" arriva a 1,1 m dal letto in due passi.
- Lungo la strada la verifica ha scartato divano e tavolo da pranzo presi per letti (YOLO 0,35–0,65).

## Esplorazione senza mappa

Senza Nav2 (o con `nav:=slam`) l'agente non usa la mappa della casa (`src/go2_sim_worlds/maps/house_world_map.{pgm,yaml}`): una richiesta come "vai in camera da letto" diventa "trova il letto e avvicinati".

Il giro di ricerca è fatto di rotazioni da 90° (5 rotazioni per un giro completo). La camera vede ~110° e sui frame della casa Kimi-K2.6 trova i bersagli anche al bordo dell'immagine (87% fra 45° e 55° dal centro), quindi ogni direzione cade entro ±45° in almeno una vista. Con i passi da 45° di prima un giro costava 9 rotazioni.

Se il bersaglio non compare durante un giro completo, il controller (`policy.ts`) fa esplorare il robot (studio completo, misure e limiti: [ESPLORAZIONE_GRAFO.md](ESPLORAZIONE_GRAFO.md)):

- di default (`NEBIUS_EXPLORE_CHOICE=open`) prima le porte riportate da almeno due frame dello stesso giro, altrimenti la direzione più aperta (letture oltre 5 m contano uguale), penalizzando quella da cui il robot arriva; le direzioni trovate bloccate vengono scartate;
- con `NEBIUS_EXPLORE_CHOICE=vision` (solo modelli a box, come Kimi-K2.6) il robot segue un **grafo di luoghi**: ogni punto in cui finisce un giro è un nodo, con la posizione stimata sommando i movimenti eseguiti (nessuna posa reale, nessuna odometria) e le direzioni già esplorate da lì; un giro entro 1,5 m da un luogo noto è lo stesso luogo. Il modello vision riceve in un'unica immagine le viste del giro, con le direzioni già esplorate segnate, e sceglie la vista e il punto verso cui camminare (una chiamata in più per giro, ~2 s); se non risponde vale la regola di default. Sui frame della casa questa scelta avvicina alla zona del bersaglio nel 58–65% dei casi contro il 38%, ma a ciclo chiuso, su 16 corse, entrambe le modalità hanno raggiunto un bersaglio dell'ala ovest 1 volta su 5: rotazioni bloccate dai mobili bassi e deriva della direzione stimata pesano più della scelta;
- si gira, avanza fino a 2,5 m con i soliti limiti e rifà il giro da lì;
- dopo 7 esplorazioni (8 con le frontiere di `nav:=slam`), o se nessuna direzione ha almeno 1,5 m liberi, termina con insuccesso.

**Falsi positivi.** Nella casa YOLO scambia il divano bianco per un letto (0,4–0,55) e il modello vision può "vedere" il bersaglio in un oggetto simile (con MiniCPM-V il letto, con Kimi una porta a soffietto per un armadio). Per questo:

- i rilevamenti YOLO sotto 0,8 (`NEBIUS_VERIFY_BELOW_CONFIDENCE`) sono verificati dal modello vision sul ritaglio ("un divano non è un letto"); la soglia era 0,6, ma il divano è arrivato a 0,65 come letto;
- gli avvistamenti del modello vision sono ricontrollati sul ritaglio quando verrebbero confermati e prima dell'arrivo;
- le segnalazioni deboli (solo modello vision, o YOLO sotto 0,8) contano solo se si ripetono nel frame successivo: fino ad allora giro ed esplorazione non vengono azzerati e `finish(success)` è rifiutato.
- una segnalazione non confermata non chiude mai la ricerca: né come arrivo né come "percorso bloccato" (il modello vision ha visto un "letto" a 0,44 m che era il divano davanti al robot); il robot continua a cercare ed esplorare.
- una segnalazione non confermata che sparisce due volte quando il robot si gira a guardarla, alla stessa direzione (±20°), viene ignorata finché il robot resta in quel punto (log `[Perception] ignoring the sighting`). Un divano "visto" come letto solo al bordo dell'immagine faceva girare il robot avanti e indietro per ~20 passi.
- una segnalazione che comincia già alla distanza d'arrivo con il riquadro che riempie l'immagine (≥ 60% dell'altezza) non viene confermata dalla sola ripetizione, salvo se il bersaglio era stato visto più lontano nella stessa direzione nelle ultime 3 osservazioni. Esplorando, il robot era finito a 0,37 m dal divano e due frame l'avevano preso per il letto.

**Limite noto.** Senza mappa la stanza giusta non è garantita. Nella casa la camera è a ~6 m dal punto di partenza, ma attraverso un varco a sud-ovest, mentre verso +x c'è il soggiorno aperto (5–8 m liberi): l'esplorazione tende a partire dalla parte sbagliata. Nella serie A/B del 13 ottobre (16 corse, arrivo verificato sulla posa reale) letto e scrivania dallo spawn sono stati raggiunti 1 volta su 5 in ciascuna modalità; il frigorifero, che si vede già dal primo giro, 5 volte su 6. Il robot si incastra contro oggetti bassi che il corridoio di profondità non vede (cestino, tavolino, manubrio): lì le rotazioni riescono in mediana al 40% e la direzione stimata deriva fino a 180°. Numeri e prossimi passi (direzione dall'IMU, ostacoli bassi) in [ESPLORAZIONE_GRAFO.md](ESPLORAZIONE_GRAFO.md).

Nemotron vede `exploring` ed `explorations` nell'osservazione e chiama `explore`; se insiste con `search` dopo il giro, il controller lo rifiuta e la policy deterministica esegue l'esplorazione. I log `[Explore]` mostrano la fase, la direzione scelta e lo spazio libero misurato per ogni direzione.

## Calibrazione della simulazione

Misurata con la posa reale `/gz/dottorcane/pose`:

- profondità nel box dell'idrante coerente con la distanza reale (6,17 m misurati contro 6,56 m centro-centro);
- movimenti, con la diagnostica `AGENTICROS_DEBUG_POSE_TOPIC` (ottobre 2026, casa headless, real time factor 1,0): con le efficienze di prima (0,65 / 0,7) −90° comandati diventavano −106° e 1 m diventava 1,2 m.

`run_nebius_agent.sh` imposta quindi `NEBIUS_TURN_EFFICIENCY=0.77` e `NEBIUS_FORWARD_EFFICIENCY=0.84`: −90° → −91…−93°, 1 m → 0,97 m, con una deriva a destra di ~2° per pezzo di avanzamento. I comandi sono temporizzati in secondi reali: se la sim gira più lenta (real time factor < 1, per esempio con la GUI), le efficienze vanno moltiplicate per il fattore. Il ciclo chiuso corregge l'errore residuo nell'avvicinamento; per il grafo dei luoghi, che si basa sulle direzioni stimate, la calibrazione conta di più.

## Perché non `run_mission`

Il planner delle missioni AgenticROS è a regole, senza LLM: esegue una lista fissa di passi una sola volta, senza verificare l'obiettivo. Il passo di avvicinamento generato pubblica su `/cmd_vel` (non sul topic del Go2), con un segno di sterzata invertito e un template che non viene risolto. Il ciclo fino all'obiettivo vive quindi nell'adapter, e usa i tool AgenticROS come primitive.

## Modifiche ad AgenticROS (submodule `tools/agenticros`)

- `agenticros-nebius`: il vecchio flusso a un solo passo è sostituito dal ciclo (`agent.ts`, `perception.ts`, `policy.ts`, `robot.ts`, test in `__tests__/`).
- `agenticros-nebius`, percezione: modalità `NEBIUS_PERCEPTION=yolo|vlm`, profili del modello vision e parser JSON robusto (`vision.ts`), box in frazioni con Kimi-K2.6, guardie contro gli arrivi falsi. Vedi [CHANGELOG.md](CHANGELOG.md).
- `object-detection`: `detectClassTiled` (usato anche da `ros2_find_object`, che prima non trovava l'idrante a distanza) e correzione del clipping dei box.
- `ros2_depth_distance`: parametri ROI `roi_*` negli adapter Claude Code/MCP, OpenClaw e Gemini.
- Arresto sicuro con Ctrl-C: il transport locale rimuove l'handler SIGINT di rclnodejs (che chiudeva il contesto ROS prima degli stop), e il server MCP, alla chiusura, interrompe i `ros2_move_for` in corso e invia `ros2_estop`. Prima il controller CHAMP restava con l'ultimo `cmd_vel` e il robot continuava a muoversi.
- Crash del server MCP (`Napi::Error: Invalid argument`, SIGABRT, poi `MCP error -32000: Connection closed` nell'agente): `EntityCache` del transport locale distruggeva la subscription dentro la sua stessa callback (snapshot e profondità leggono un solo messaggio). Ora la distruzione è rimandata con `setImmediate`; 160 chiamate snapshot/profondità/movimento senza crash.
- Azioni ROS nel transport locale: `sendActionGoal` usava una firma di `ActionClient.sendGoal` a callback che rclnodejs 1.8 non ha (e passava la classe invece del nome del tipo), quindi `ros2_action_goal` non arrivava mai al risultato. Ora usa goal handle e `getResult()`, restituisce lo stato reale (`succeeded`, `aborted`, `canceled`, `rejected`), ha un timeout configurabile (default 600 s, poi annulla il goal) e `cancelAllActionGoals()`.
- `cancelNavigation` (core) e `ros2_estop` che annulla la navigazione; nuovo tool `ros2_list_actions`.
- Posti con nome: `AGENTICROS_PLACES_PATH` per usare un file per mappa, campo `description`; `skillPaths` relativi al file di config.
- Server MCP orfani: se il client terminava senza segnale (kill, crash) il server restava vivo con il suo nodo ROS. Ora si chiude quando lo stdin si chiude, dopo l'estop.
- Esplorazione senza mappa con un grafo di luoghi e scelta della direzione da parte del modello vision (`policy.ts`, `perception.ts`, `agent.ts`), guardia sugli avvistamenti che cominciano già vicini: vedi [ESPLORAZIONE_GRAFO.md](ESPLORAZIONE_GRAFO.md).
- `agenticros_explore` svuotava la lista dei goal recenti a fine azione: con una frontiera per azione riproponeva sempre la stessa frontiera irraggiungibile (dietro il divano). Ora ricorda gli ultimi 16 goal tra un'azione e l'altra.

## Latenza

Per passo: snapshot ~0,3 s (dopo il primo), YOLO + vision in parallelo ~1–1,5 s (modalità `vlm`: Kimi-K2.6 ~1–1,3 s, percezione 1,7–1,9 s in tutto), profondità ~0,5 s, Nemotron Lightning ~0,4 s, movimento fino a 8 s. Ricerca e avvicinamento all'idrante dalla posizione iniziale (~6,4 m, fuori dal campo visivo): circa 15 passi.
