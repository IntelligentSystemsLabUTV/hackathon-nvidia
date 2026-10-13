# Esplorazione senza mappa con un grafo di luoghi

Ottobre 2026. Come il robot sceglie dove andare quando non ha una mappa (`nav:=none`) e il bersaglio non è nel campo visivo: l'idea di partenza (stanze come nodi, porte come archi), cosa sa davvero vedere il modello vision, cosa è stato implementato e come si comporta nella casa simulata. Numeri grezzi e script: [`scripts/vision_eval/RISULTATI.md`](../scripts/vision_eval/RISULTATI.md).

La versione definitiva costruirà prima una mappa e poi la userà (Nav2, `nav:=map`): questa è la modalità di riserva quando la mappa non c'è.

## In breve

- **Offline Kimi sceglie la direzione meglio della regola dello spazio libero.** Dopo un giro senza bersaglio, il 58–65% delle camminate scelte da Kimi avvicina alla stanza del bersaglio, contro il 38%; per l'ala ovest 74–82% contro 21%.
- **A ciclo chiuso il vantaggio non si vede.** Su 16 corse nella casa simulata, 8 per modalità, nelle missioni che richiedono di esplorare (letto e scrivania dallo spawn) entrambe le modalità arrivano **1 volta su 5**. Per questo il default di `NEBIUS_EXPLORE_CHOICE` è `open`; `vision` resta disponibile.
- **Il collo di bottiglia è il corpo, non la scelta.** Vicino a oggetti bassi che la profondità frontale non vede (cestino, tavolino, manubrio), il robot si incastra: le rotazioni comandate a meno di 0,4 m da un ostacolo riescono in mediana al 40%. La direzione stimata conta ogni comando come eseguito, quindi deriva fino a 180° e il grafo dei luoghi perde senso.
- **Le corse hanno fatto emergere otto difetti, tutti corretti:** due falsi arrivi sul divano, un letto perso ricentrando, la calibrazione dei movimenti sbagliata del 20%, il robot fermo davanti al telaio di una vetrata (due casi), una deviazione senza spazio per svoltare e un timeout della camera che chiudeva il compito. Resta aperto un falso arrivo semantico: il tavolino preso per una scrivania.

## Il problema

Senza mappa l'agente cerca il bersaglio con un giro sul posto (5 rotazioni da 90°). Se non lo vede, esplora: cammina fino a 2,5 m e rifà il giro da lì. Prima di questo lavoro la direzione era la porta riportata da almeno due viste del giro oppure, quasi sempre, la direzione con più spazio libero davanti. Nella casa la direzione più aperta porta quasi sempre nell'open space verso est (5–8 m liberi), mentre la camera da letto è a ovest dietro un varco. Così "vai in camera da letto" falliva in 2 corse su 2 con i passi da 45° e dipendeva dalla prima esplorazione con quelli da 90°.

## La casa vista come grafo

![Topologia della casa](img/casa-topologia.png)

L'idea era: le stanze sono i nodi, le porte sono gli archi, il robot sceglie la porta che porta alla stanza del bersaglio. La casa però non è fatta così:

- **il centro e l'est sono un unico open space** (ingresso, palestra, soggiorno, zona finestre, sala da pranzo, cucina): fra le "stanze" non ci sono porte, al massimo un'apertura larga 6,3 m;
- **l'ala ovest** (camera da letto e seconda stanza, separate da un muro alto 1,9 m con due varchi alle estremità) si raggiunge da **un solo varco** largo 3,4 m (x = −2,46, y fra −2,8 e 0,59);
- ai due lati del varco ci sono **porte a soffietto di vetro, chiuse** (vetro smerigliato con telaio nero a ovest, telaio di legno a est): sembrano porte, ma non si attraversano;
- dallo spawn il letto non si vede; il varco è 3 m a sud-ovest, ai margini di due viste del giro.

I nodi utili quindi non sono stanze ma **luoghi**: i punti in cui il robot fa un giro. Gli archi sono le direzioni percorse da ciascun luogo, attraverso un varco o nello spazio aperto.

## Cosa sa vedere il modello vision (misure offline)

Sui 56 frame della casa (7 punti × 8 direzioni) con la posa reale, la topologia vera della casa ([`house_topology.json`](../scripts/vision_eval/house_topology.json)) è stata proiettata in ogni frame: quali passaggi, vetrate e finestre sono visibili, a che angolo e a che distanza. Script: `topo_eval.py` ed `explore_choice_eval.py` in `scripts/vision_eval/`.

### Porte e passaggi

| Prompt di Kimi-K2.6 | "Aperte" su un passaggio vero | Vetrate chiuse dichiarate aperte | Passaggi riportati | Latenza |
|---|---|---|---|---|
| attuale (lista di porte) | 48% | 42 | 27% | 2,49 s |
| con il tipo (aperta, vetro, chiusa) | 64% | 11 | 31% | 2,74 s |

![Aperture classificate da Kimi](img/aperture-kimi.jpg)

*Dall'ingresso. A sinistra Kimi chiama "open" la vetrata sud e non riporta il varco; a destra classifica bene vetrata e varco.*

Chiedere il tipo di apertura dimezza le vetrate scambiate per porte, ma una porta "aperta" su tre non è un passaggio vero e due passaggi su tre non vengono riportati. Su un grafo di porte fatto così il robot sbaglierebbe arco spesso.

### Stanze e "cosa c'è oltre"

- **Tipo di zona**: dalla camera da letto Kimi risponde "living room" 11 volte e "bedroom" 10. Le viste verso il varco mostrano il soggiorno, e una votazione sul giro sbaglierebbe stanza.
- **Cosa c'è oltre un varco**: per il varco verso la camera visto dal centro non nomina mai camera o letto (0/9: "adjacent room with chandelier", "area beyond divider"). Dal centro, attraverso il varco, si vede solo un corridoio con un muretto di mattoni.

Etichette di stanza e "cosa c'è oltre" non sono abbastanza affidabili per decidere: non sono state adottate.

### Dove andare dopo un giro

La domanda che conta davvero è un'altra: dopo un giro senza bersaglio, **in che direzione camminare?** Per 65 casi (7 punti di cattura × bersagli che stanno solo in altre zone) è stato misurato di quanto una camminata di 2,5 m accorcia il percorso a piedi verso la zona del bersaglio (distanza geodetica sulla mappa, fermandosi a 0,45 m dagli ostacoli, vetrate comprese).

| Chi sceglie | Avvicinano > 0,5 m | Allontanano > 0,5 m | Progresso medio |
|---|---|---|---|
| **Kimi, sul mosaico delle viste del giro: vista + punto** | **58–65%** | **8–12%** | **+0,83…+1,04 m** |
| Kimi, elencando prima le aperture di ogni vista | 65% | 20% | +0,88 m |
| Nemotron, sulle descrizioni testuali delle viste | 25% | 22% | −0,14 m |
| la vista con una porta "aperta" | 34% | 29% | −0,07 m |
| la direzione più aperta (regola precedente) | 38% | 42% | −0,16 m |
| una vista a caso | — | — | −0,25 m |

Per i bersagli dell'ala ovest (letto, armadio, comodino, scrivania) Kimi avvicina nel 74–82% dei casi contro il 21% della direzione più aperta; per quelli dell'open space la direzione più aperta resta migliore (63% contro 37–41%), ma lì il bersaglio di solito si vede già durante il giro.

![Scelta dalla palestra](img/mosaico-palestra-letto.jpg)

*Dalla palestra, bersaglio "letto": Kimi sceglie la vista verso il varco ovest (fascia verde) e un punto poco a destra.*

![Scelta dallo spawn](img/mosaico-spawn-letto.jpg)

*Dallo spawn, bersaglio "letto": Kimi sceglie la vetrata (vista 3). Il varco vero è a destra nella vista 2, accanto al muretto di mattoni.*

Il punto debole è proprio lo spawn: con le 4 viste del giro del robot e 6 ripetizioni, per letto, armadio e scrivania Kimi non sceglie mai la direzione giusta (0/6: porte a vetri con telaio di legno, prese per porte di camere, oppure la cucina), mentre per il frigorifero la indovina sempre (6/6). Dire nel prompt che le vetrate non si attraversano, o di preferire le zone che non si vedono, non cambia nulla; nemmeno farle elencare prima di scegliere.

## Cosa è stato implementato

### Grafo dei luoghi (`policy.ts`)

- **Posizione stimata** (`xM`, `yM`): somma degli avanzamenti eseguiti lungo la direzione stimata. Niente posa reale e niente odometria: in simulazione `/dottorcane/odom` è la posa di Gazebo e non va passata all'agente.
- **Luoghi** (`places`): un nodo per ogni punto in cui il robot finisce un giro senza bersaglio; un giro entro 1,5 m da un luogo noto è lo stesso luogo (`enterPlace`).
- **Archi esplorati** (`exploredDeg`): le direzioni già prese da quel luogo e la direzione opposta a quella da cui il robot è arrivato.
- **Direzione suggerita** (`suggestedHeadingDeg`): se c'è e non è bloccata, `chooseExploreHeading` la usa prima delle porte e dello spazio libero. Dopo un viaggio Nav2 (`nav:=slam`) posizione e grafo ripartono da zero.

### Scelta della direzione (`perception.ts`, `agent.ts`)

Alla fine di ogni giro senza bersaglio, `suggestExploration` compone le viste del giro (l'ultima per ogni direzione, 768×432 ciascuna) in un'unica immagine, etichetta ognuna con numero, direzione rispetto al robot ed "(explored)" se punta verso un arco già esplorato, e chiede a Kimi (`chooseExploreView`, JSON strutturato) la vista e il punto `x` verso cui camminare. La direzione è quella della vista più l'angolo di `x` nella camera. Costa una chiamata in più per giro (~2 s); se la risposta manca o non è valida, si usano porte e spazio libero come prima.

Log: `[Graph] place 2 of 2 at (1.8, -1.7) m, explored headings [136] deg` e `[Explore] vision model: view 3 (0 deg), x 0.85 -> heading -148 deg ...: <motivo>`.

Si attiva con `NEBIUS_EXPLORE_CHOICE=vision`, solo con un modello vision a box (Kimi-K2.6); un modello a colonne (MiniCPM-V) non sa indicare un varco. Il default è `open`, la regola precedente: nelle prove a ciclo chiuso, più sotto, la scelta di Kimi non ha portato più arrivi e costa una chiamata in più per giro.

### Calibrazione dei movimenti (`run_nebius_agent.sh`)

Le direzioni delle viste e del grafo sono stimate dai movimenti comandati, quindi la calibrazione conta. Misurata con la diagnostica `AGENTICROS_DEBUG_POSE_TOPIC` (solo log), la sim attuale con le efficienze 0,65 / 0,7 girava e camminava circa il 20% più del comandato: −90° comandati diventavano −106°, quindi la direzione stimata derivava di ~16° a ogni rotazione da 90°.

| Efficienze | −90° | −45° | +20° | 1 m | 0,5 m |
|---|---|---|---|---|---|
| 0,65 / 0,7 (prima) | −106° | −54° | +25° | 1,20 m | 0,59 m |
| **0,77 / 0,84** (ora) | −91…−93° | −46° | +18° | 0,97 m | 0,51 m |

Misure headless con real time factor 1,0. I comandi sono temporizzati in secondi reali: se la sim gira più lenta (per esempio con la GUI), le due efficienze vanno moltiplicate per il real time factor (`gz topic -e -n 1 -t /stats`).

### Guardia: avvistamento che parte già vicino

In una prova, esplorando, il robot è finito a 0,37 m dal divano bianco ad angolo: il riquadro riempiva il 90% dell'immagine e sia Kimi sia la verifica sul ritaglio l'hanno preso per un letto ("imbottitura con cuscini"), due frame di fila, arrivo dichiarato a 7,4 m dal letto vero. Ora un avvistamento che **comincia** già alla distanza d'arrivo (≤ 1,35 m) con il riquadro alto almeno il 60% dell'immagine non viene confermato dalla sola ripetizione (`closeFirstSighting`): il robot continua a cercare, come già fa con un avvistamento non confermato davanti a un ostacolo. Non vale se il bersaglio era stato visto più lontano nella stessa direzione (±25°) nelle ultime 3 osservazioni: è la fine di un avvicinamento con un frame mancato.

Nella serie A/B la guardia è stata aggirata una volta. Il divano, visto per la prima volta con il riquadro alto il 70% dell'immagine, aveva distanza ignota, perché la profondità leggeva un cuscino più vicino del riquadro. Al frame dopo era a 0,77 m ed è stato confermato come letto. Ora anche un primo avvistamento a distanza ignota che riempie l'immagine conta come "già vicino".

### Avvicinamento: niente ricentraggi inutili

In una corsa il robot, arrivato nel soggiorno, ha visto e confermato il letto attraverso il varco a 7,4 m, 5,5° a destra. Nemotron ha chiesto due volte `face_target` (rotazioni di 5°) invece di avvicinarsi; al terzo frame Kimi non ha visto il letto, piccolo e lontano, e il robot ha ricominciato il giro perdendolo. Ora `face_target` entro la tolleranza di allineamento (12°) viene rifiutato con l'indicazione di usare `approach_target`, che allinea e avanza da solo (1 m quando il bersaglio è lontano).

### Bloccato contro uno spigolo: la deviazione

In due corse, una per modalità, il robot è arrivato al varco giusto, ma la linea retta verso il letto passava sullo spigolo della porta a soffietto nord. Con il fianco contro il telaio non riusciva né a girare né ad avanzare, mentre la profondità vedeva spazio libero oltre il varco: in una corsa è rimasto lì 45 passi, a 0,26 m dalla vetrata e a 4,3 m dal letto.

Ora il controller confronta ogni movimento con l'immagine successiva (`lastMotion`, `ineffectiveMotions`):

- dopo una rotazione di almeno 8° il bersaglio deve spostarsi nell'immagine di almeno il 35% della rotazione;
- dopo un avanzamento di almeno 0,5 m deve avvicinarsi o cambiare direzione.

Due movimenti di fila senza effetto significano che il corpo è bloccato. Il robot allora gira di 40° dal lato opposto al bersaglio, dove di solito sta lo spigolo contro cui ha cercato di girare, avanza fino a 0,7 m se c'è spazio e riprende l'avvicinamento (`detour`, log `[Decision] … (stuck: turning left to go around the obstacle)`). Funziona solo con il bersaglio visibile, perché è il bersaglio a dire se il movimento è avvenuto.

In una prova successiva, partita davanti al telaio, è emerso il caso opposto: i movimenti funzionavano, ma a 0,48 m dal telaio non c'era più spazio per avanzare. Il letto era confermato a 3,2 m, a +10°, e il robot si è arreso con "Il percorso verso il bersaglio è bloccato.", mentre il varco libero era 60° più a sinistra. Ora, con il bersaglio confermato, centrato e non ancora raggiunto, e senza spazio per avanzare, il robot gira e cammina come sopra, prima **dal lato del bersaglio** e, se si blocca di nuovo, dall'altro (log `(blocked: …)`). Qui girare dal lato opposto lo avrebbe portato contro la vetrata. Si arrende solo dopo 3 deviazioni dallo stesso punto. Un avvistamento non confermato davanti a un ostacolo resta escluso: come prima, il robot continua a cercare (la guardia del divano).

Nella serie A/B la deviazione è scattata davanti a un divano, ma dopo la svolta di 40° il divano era ancora a 0,43 m e la corsa è finita con "Nessuna azione sicura disponibile.". Ora, se dopo la svolta non c'è spazio per camminare, il robot gira subito di 80° dall'altro lato. Finite le deviazioni, il messaggio è "Il percorso verso il bersaglio è bloccato.".

### Camera: un timeout non interrompe più il compito

In una corsa uno snapshot della camera è andato in timeout al passo 57 e l'errore ha chiuso l'intero compito. Ora conta come un'osservazione mancata: nessun movimento, si riprova, e il compito si interrompe solo dopo 3 fallimenti di fila, come già accade se non risponde il modello vision.

### Cosa non è stato adottato

- il tipo di apertura nel prompt di ogni passo (+10% di latenza, bersagli trovati 83% contro 86%, non significativo) e il grafo di porte costruito su di esso: troppi errori sugli archi;
- tipo di zona e "cosa c'è oltre": non affidabili (vedi sopra);
- la scelta di Nemotron sulle descrizioni testuali: appena meglio del caso (vista giusta 32–34% contro 28%).

## Prove a ciclo chiuso

Serie A/B del 13 ottobre 2026. Casa simulata headless, `nav:=none`, real time factor 1,0, codice con guardie, deviazione e snapshot robusto (prima delle due correzioni nate dalla serie stessa). 16 corse alternate fra `vision` e `open`, limite di 80 passi e 600 s. L'arrivo è verificato sulla posa reale di Gazebo, registrata fuori dall'agente insieme alla traiettoria.

| Missione (partenza) | `vision` | `open` |
|---|---|---|
| letto, dallo spawn | **1 su 3**: arrivato in 56 passi; fallito a est dopo 7 esplorazioni; falso arrivo sul divano | **1 su 3**: arrivato in 63 passi; 2 volte 80 passi senza uscire dal soggiorno |
| scrivania, dallo spawn | **0 su 2**: falso arrivo sul tavolino, preso per "reception desk"; tempo esaurito a est | **0 su 2**: 7 e 6 esplorazioni fra centro ed est |
| frigorifero, dalla camera | 2 su 3 (19 e 25 passi); 1 fermata davanti al divano | 3 su 3 (26–31 passi) |
| **missioni con esplorazione** | **1 su 5** | **1 su 5** |

Il frigorifero si vede già durante il primo giro, quindi quelle corse non esplorano e non dicono nulla sulla scelta della direzione.

![Traiettorie della serie A/B](img/traiettorie-ab.png)

*Traiettorie vere delle 9 corse con esplorazione registrate (la prima è partita prima del registratore): `vision` in blu, `open` in arancione. I punti rossi sono le rotazioni che hanno girato meno del 70% del comando.*

Cosa mostrano le corse:

- **L'ala ovest è stata raggiunta 1 volta per modalità.** Dallo spawn Kimi ha mandato il robot a est o al centro, come nelle misure offline (0/6 per letto, armadio e scrivania). La regola dello spazio libero porta quasi sempre nell'open space.
- **Le rotazioni falliscono vicino agli oggetti bassi.** Su 330 rotazioni comandate di almeno 60°, ecco la frazione girata davvero, in base alla distanza del centro del robot dall'ostacolo più vicino della mappa:

  | Distanza dall'ostacolo | Rotazioni | Girato (mediana) | Sotto il 70% |
  |---|---|---|---|
  | < 0,4 m | 85 | 40% | 61 |
  | 0,4–0,8 m | 56 | 97% | 5 |
  | 0,8–1,2 m | 87 | 97% | 9 |
  | > 1,2 m | 102 | 97% | 0 |

  Gli oggetti sono il cestino del soggiorno, il tavolino, i mobili bassi contro la parete sud e il manubrio della palestra, che non compare nemmeno nella mappa (i 9 casi fra 0,8 e 1,2 m). Il corridoio di profondità davanti al robot guarda sopra l'orizzonte e non li vede, quindi il robot ci cammina contro e poi non riesce a girare.
- **La direzione stimata deriva con le rotazioni fallite.** In 3 corse su 9, alla fine, la direzione stimata differiva da quella vera di più di 140°; nelle corse `vision` la posizione stimata dei luoghi sbagliava fino a 3,2 m in una e fino a 10 m in un'altra. Con una deriva così le direzioni "già esplorate" e il riconoscimento dei luoghi non corrispondono più alla casa.
- **Falsi arrivi**: 2 corse `vision` su 8 sono finite su un oggetto sbagliato (divano per letto, tavolino per scrivania). Il primo è corretto dalla guardia estesa; il secondo è un errore semantico del modello vision, confermato anche dalla verifica sul ritaglio, e resta aperto.

Le prove singole allo spigolo fatte prima della serie, partendo a 0,5–1,7 m dal varco ovest, sono arrivate al letto 3 volte su 4 (2,23–2,40 m dal centro del letto, cioè sul bordo). La quarta si è arresa davanti al telaio e ha portato alla deviazione per percorso bloccato.

## Limiti

- **Lo spawn della casa** resta il caso peggiore per la scelta di Kimi: le porte a vetri con telaio di legno sembrano porte di camere e il varco vero è ai margini di due viste.
- **Gli oggetti bassi non si vedono**: il corridoio di profondità davanti al robot guarda sopra l'orizzonte, quindi cestino, tavolino e manubrio non contano come ostacoli. Il robot ci cammina contro e poi le rotazioni falliscono (vedi la tabella sopra).
- **La direzione e la posizione stimate derivano**: sono la somma dei comandi, e una rotazione bloccata conta come eseguita. Anche senza ostacoli la camminata devia di ~2° per pezzo da 3 s e una rotazione da 90° sbaglia di ±5°. Vicino ai mobili l'errore arriva a 180° in una corsa, e il riconoscimento dei luoghi già visti (1,5 m) non regge più.
- **Falsi positivi semantici**: Kimi e la verifica sul ritaglio hanno preso un tavolino basso per una scrivania ("reception desk or counter").
- **Il vetro**: la profondità simulata vede attraverso le vetrate (ma non i telai), quindi una stanza dietro il vetro sembra raggiungibile; il letto visto attraverso una vetrata attira il robot contro il vetro.
- **Il modello vision non è deterministico**: anche a temperatura 0 la stessa domanda può dare scelte diverse.
- Con `nav:=map` tutto questo non serve: Nav2 porta il robot nella stanza giusta al primo colpo.

## Prossimi passi possibili

In ordine di guadagno atteso; nessuno è ancora implementato né misurato.

1. **Direzione dall'IMU.** La camera ZED pubblica un'IMU (`/dottorcane/slam/zed_x_driver/imu`). La direzione integrata dalla velocità angolare non risente delle rotazioni bloccate, e un confronto fra comando e IMU dice subito se il robot non ha girato: sarebbe il segnale per indietreggiare. È un sensore di bordo, non la posa reale. Va verificato quanto deriva in simulazione e se il suo orientamento non sia, di fatto, la posa vera di Gazebo.
2. **Ostacoli bassi.** Campionare la profondità anche sotto l'orizzonte, in fasce, e confrontarla con la distanza a cui ogni fascia vedrebbe il pavimento (`floorImageY` in `policy.ts`): una lettura più corta è un ostacolo.
3. Ripetere la serie A/B: con il corpo che gira davvero, il vantaggio offline di Kimi potrebbe comparire anche a ciclo chiuso.

## Come ripetere le misure

```bash
cd ~/workspace/scripts/vision_eval
# aperture e zone sui 56 frame (servono frame e verità a terra locali, vedi README)
../../.venv/bin/python eval_vlm.py kimi26_exits_1024
../../.venv/bin/python topo_eval.py kimi26_final_1024 kimi26_exits_1024
# dove esplorare dopo un giro (65 casi)
../../.venv/bin/python explore_choice_eval.py kimi26_exits_1024
# confronto A/B a ciclo chiuso (sim della casa headless, nav:=none); registra anche la posa vera
bash -ic './closed_loop_matrix.sh spec.txt'
# traiettorie, deriva del grafo, rotazioni rispetto agli ostacoli, figura
../../.venv/bin/python closed_loop_traj.py spec.txt --rotations --plot traiettorie.png
```
