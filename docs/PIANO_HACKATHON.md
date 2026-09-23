# Piano operativo — Nebius × NVIDIA Global AI Hackathon

## Obiettivo

Realizzare un agente robotico che osserva un ambiente indoor attraverso le immagini ROS 2, ragiona con un modello NVIDIA eseguito su Nebius Token Factory e usa AgenticROS per scegliere ed eseguire azioni sul robot.

La dimostrazione parte in Gazebo con un modello simulato del Unitree Go2 e termina, se l'integrazione hardware è disponibile, sul robot reale. Il robot non riceve una mappa metrica globale: conosce luoghi, oggetti e passaggi fra stanze, mentre Nav2 mapless si occupa soltanto del movimento locale e della collision avoidance.

La sequenza centrale della demo è:

1. il robot acquisisce un'immagine da un topic ROS;
2. AgenticROS rende l'osservazione disponibile al modello su Nebius;
3. il modello descrive la stanza, identifica oggetti e passaggi e sceglie un'azione;
4. il runtime locale valida la richiesta e la esegue tramite AgenticROS;
5. il robot cambia punto di vista o stanza;
6. la nuova osservazione torna al modello, che aggiorna la propria decisione.

Il risultato da mostrare non è soltanto «il modello vede una stanza», ma «il modello non ha abbastanza informazioni, decide quale evidenza cercare e usa il robot per ottenerla».

## Perimetro dell'MVP

L'MVP comprende:

- un mondo Gazebo con almeno due stanze collegate;
- oggetti visivamente distintivi distribuiti nelle stanze;
- camera RGB e, quando utile al movimento locale, depth camera o LiDAR;
- un modello vision su Nebius Token Factory per il grounding delle immagini;
- un modello NVIDIA Nemotron su Nebius per ragionamento e tool calling;
- un ciclo di tool calling che collega il modello alle capability AgenticROS;
- un piccolo grafo semantico di luoghi e transizioni, privo di coordinate globali;
- un runtime Rust che conserva stato, valida le risposte e coordina il ciclo;
- almeno un'azione di osservazione e un'azione di movimento semantico;
- log o interfaccia che mostrino osservazione, decisione, azione e risultato.

Non fanno parte del percorso critico:

- compilatore missione → Behavior Tree;
- generazione dinamica di Behavior Tree;
- costruzione autonoma di una mappa metrica;
- esplorazione completa di edifici grandi;
- addestramento di un detector proprietario;
- crescita open-set completa del grafo.

Nav2 può usare internamente i propri Behavior Tree. Ciò è separato dal compilatore BT applicativo che viene rimandato.

## Architettura

```text
Gazebo / Go2
    │
    │ RGB, depth, LiDAR, odometria
    ▼
ROS 2
    │
    ▼
AgenticROS
    │   snapshot, capability e risultati delle azioni
    ▼
Runtime agente locale in Rust
    ├── stato della sessione
    ├── grafo semantico e belief
    ├── validazione delle azioni
    ├── timeout, retry e cancellazione
    └── client OpenAI-compatible
             │
             ▼
    Nebius Token Factory
    modello vision + NVIDIA Nemotron
             │
             ▼
    testo strutturato / tool call
             │
             ▼
Runtime Rust → AgenticROS → capability di movimento → Nav2 mapless
```

Nebius non accede direttamente ai topic ROS. Il runtime locale legge uno snapshot attraverso AgenticROS, lo codifica nel formato richiesto dall'API e invia soltanto l'osservazione necessaria. Il modello restituisce una risposta o una tool call. Il runtime valida la richiesta prima di inoltrarla ad AgenticROS.

Controllo del movimento, arresto, collision avoidance e timeout rimangono locali. Una perdita di rete non deve lasciare il robot in movimento.

## Responsabilità dei componenti

### Gazebo e ROS 2

Il simulatore produce immagini e dati sensoriali realistici. Il mondo deve contenere stanze, porte e oggetti riconoscibili dalla camera del robot.

Il mondo Gazebo contiene necessariamente geometria e pose per eseguire la simulazione; questi dati non devono essere esposti all'agente come mappa globale o ground truth. L'agente riceve soltanto sensori e risultati delle capability.

La simulazione AgenticROS esistente offre già un AMR differenziale, camera RGB-D, LiDAR e mondo indoor. Non contiene ancora il Go2 e la configurazione Nav2 fornita usa mappa statica e AMCL. Il lavoro di mobilità deve quindi sostituire il robot simulato e la configurazione di navigazione senza riutilizzare la mappa globale come scorciatoia.

### AgenticROS

AgenticROS è il ponte tra l'agente e ROS 2. Fornisce lo snapshot della camera, espone capability tipizzate e inoltra le azioni ai nodi locali.

Per l'MVP sono sufficienti queste capability semantiche:

| Capability | Scopo | Risultato minimo |
|---|---|---|
| `observe_place` | Acquisire un'immagine corrente | immagine, timestamp, observation ID |
| `look_around` | Cambiare il punto di vista localmente | completato, fallito o cancellato |
| `inspect_landmark` | Cercare meglio un oggetto indicato | nuova osservazione e risultato |
| `find_transition` | Individuare un passaggio visibile | transition ID e stato |
| `traverse_transition` | Attraversare un passaggio identificato | attraversato, bloccato, fallito o cancellato |
| `get_location_belief` | Leggere le ipotesi correnti | luoghi candidati e confidenza interna |

Le capability rivolte al modello non devono accettare coordinate globali o pubblicazioni arbitrarie su `cmd_vel`. Le azioni di basso livello restano interne al componente di mobilità.

### Runtime in Rust

Rust viene usato per il coordinatore locale e il core semantico perché questi componenti hanno stato, transizioni, errori e contratti che devono essere espliciti e testabili.

Il runtime deve:

- chiamare l'API OpenAI-compatible di Nebius;
- inviare immagini e contesto semantico;
- dichiarare al modello soltanto gli strumenti consentiti;
- interpretare tool call o output JSON strutturati;
- rifiutare azioni sconosciute o argomenti non validi;
- invocare AgenticROS;
- restituire al modello il risultato dell'azione;
- mantenere grafo, belief e cronologia dell'episodio;
- applicare timeout, limite di passi e cancellazione;
- salvare una traccia riproducibile della demo.

Il core semantico deve rimanere indipendente da ROS e Nebius, così può essere testato con osservazioni registrate.

Una possibile struttura è:

```text
crates/
  semantic-core/       tipi, grafo, belief, scelta dell'evidenza
  nebius-agent/        client Token Factory e ciclo di tool calling
  semantic-runtime/    coordinamento, policy e adapter AgenticROS
  semantic-replay/     esecuzione offline da fixture

packages/
  agenticros-semantic/ eventuale skill TypeScript sottile

interfaces/
  schemas/             JSON Schema condivisi

scenarios/
  two-rooms/           mondo logico, osservazioni e risultati attesi
  failures/            rete assente, timeout e azioni rifiutate
```

### Nebius Token Factory

Il progetto usa una chiave in `NEBIUS_API_KEY` e l'endpoint:

```text
https://api.tokenfactory.nebius.com/v1/
```

I modelli vanno scelti dal catalogo realmente disponibile per la chiave. La
configurazione iniziale sul public endpoint è:

- `openbmb/MiniCPM-V-4_5` per interpretare le immagini;
- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` per ragionamento, decisione e tool calling.

`Nemotron-Nano-V2-12b` supporta la visione, ma richiede un endpoint dedicato e
non è disponibile attraverso il public endpoint corrente. Prima di cambiare
modello bisogna verificare:

- supporto alle immagini;
- supporto al tool/function calling oppure a JSON strutturato affidabile;
- latenza su immagini ridimensionate;
- qualità nel riconoscere stanze, oggetti e porte;
- disponibilità di un modello NVIDIA valido per i requisiti dell'hackathon.

Il modello produce descrizioni, ipotesi e richieste di azione. Non produce velocità, pose globali o comandi ROS arbitrari.

### Nav2 mapless e mobilità

Questo workstream è responsabilità del componente/team di mobilità. Il contratto con il resto del progetto è una serie di azioni locali e cancellabili.

I requisiti minimi sono:

- nessun `map_server`;
- nessun AMCL;
- nessuna mappa metrica globale fornita all'agente;
- costmap locale rolling alimentata dai sensori;
- goal espressi nel frame locale;
- collision avoidance e arresto affidabile;
- feedback sull'esito dell'azione;
- possibilità di cancellare un movimento in corso;
- rilevamento o conferma dell'attraversamento di una porta.

Il runtime semantico non implementa Nav2: chiama `look_around`, `inspect_landmark` o `traverse_transition` e riceve un risultato tipizzato.

## Ciclo agente

Ogni episodio segue una macchina a stati semplice:

```text
OBSERVE
   ↓
REASON su Nebius
   ↓
risposta finale? ── sì ──> COMPLETE
   │
   no: tool call
   ↓
VALIDATE
   ├── non valida ──> restituisci errore al modello
   └── valida
          ↓
       EXECUTE tramite AgenticROS
          ↓
       risultato + nuova osservazione
          ↓
        OBSERVE / REASON
```

Il ciclo deve avere un numero massimo di passi. Se non raccoglie evidenza sufficiente, termina esplicitamente con `insufficient_evidence` invece di inventare una localizzazione.

## Scenario iniziale

Costruire due stanze collegate da una porta:

- entrambe contengono elementi comuni, per esempio tavolo, sedia e monitor;
- la prima contiene un braccio robotico;
- la seconda contiene una stampante 3D;
- dalla posa iniziale gli elementi distintivi non sono immediatamente visibili;
- una rotazione o un'ispezione aggiuntiva permette di distinguerle.

Episodio atteso:

1. il robot osserva una scena ambigua;
2. il modello dichiara che le informazioni non bastano;
3. sceglie di cercare il braccio o la stampante;
4. AgenticROS esegue `look_around` o `inspect_landmark`;
5. il modello riceve la nuova immagine e identifica la stanza;
6. il modello sceglie la transizione corretta;
7. Nav2 mapless porta il robot attraverso la porta;
8. una nuova osservazione conferma l'arrivo.

## Piano di implementazione

### Fase 0 — Accesso e verifica API

- registrarsi all'hackathon su Devpost;
- creare la chiave Token Factory;
- impostare `NEBIUS_API_KEY` soltanto nell'ambiente locale;
- elencare i modelli disponibili;
- selezionare un modello vision disponibile e un modello NVIDIA per il ragionamento;
- eseguire una richiesta testuale e una richiesta con immagine;
- verificare tool calling o JSON strutturato.

**Gate:** una foto locale viene inviata a Nebius e il modello restituisce una descrizione coerente in un formato validabile.

### Fase 1 — Visione dalla simulazione

- avviare la simulazione AgenticROS esistente;
- acquisire uno snapshot dal topic RGB tramite AgenticROS;
- convertire e ridimensionare l'immagine;
- inviarla al modello Nebius;
- salvare richiesta, latenza e risposta;
- testare almeno dieci viste note.

**Gate:** il modello riconosce in modo ripetibile gli oggetti principali presenti nelle immagini Gazebo.

### Fase 2 — Tool calling minimo

- definire gli schema di `observe_place` e `look_around`;
- implementare il ciclo modello → tool call → AgenticROS → risultato;
- accettare solo capability presenti nell'allowlist;
- aggiungere timeout, stop e limite di passi;
- registrare una traccia completa dell'episodio.

**Gate:** partendo da una singola richiesta, il modello osserva, richiede un cambio di vista e interpreta autonomamente la nuova immagine.

### Fase 3 — Ambiente semantico

- creare il mondo a due stanze;
- aggiungere oggetti discriminanti e una porta attraversabile;
- definire il grafo semantico senza coordinate globali;
- implementare `Place`, `Transition`, `Observation` e `Belief` in Rust;
- creare fixture con risposte registrate per i test offline;
- distinguere `detected`, `verified_absent` e `not_observed`.

**Gate:** il replay offline parte da un'osservazione ambigua, sceglie nuova evidenza e converge sul luogo corretto.

### Fase 4 — Movimento mapless

- ricevere dal workstream mobilità le azioni locali concordate;
- integrare `find_transition` e `traverse_transition`;
- verificare feedback, timeout e cancellazione;
- impedire l'accesso del modello a coordinate globali e `cmd_vel`;
- provare attraversamenti da pose iniziali diverse.

**Gate:** il modello sceglie una porta osservata, il robot la attraversa con Nav2 mapless e una nuova immagine conferma il cambio di stanza.

### Fase 5 — Demo e valutazione

- collegare disambiguazione e attraversamento in un unico episodio;
- mostrare a schermo immagine, descrizione, ipotesi, tool call e risultato;
- confrontare osservazione singola e osservazione attiva;
- provare perdita di rete, timeout e porta bloccata;
- registrare presto una prima versione del video;
- preparare README, setup riproducibile e spiegazione dell'uso di Nebius.

**Gate:** tre esecuzioni consecutive completano l'episodio senza intervento manuale, salvo il reset iniziale della simulazione.

## Calendario

Scadenza: 30 ottobre 2026. Il piano blocca le nuove funzionalità una settimana prima.

| Periodo | Runtime, AgenticROS e Nebius | Simulazione e semantica | Mobilità | Deliverable |
|---|---|---|---|---|
| 23–25 settembre | Chiave API, catalogo modelli, test testo/immagine | Definizione scenario a due stanze | Contratto delle azioni locali | Prima immagine interpretata da Nebius |
| 26 settembre–2 ottobre | Client Rust, schema output, log e fixture | Snapshot Gazebo, oggetti distintivi | Prototipo costmap rolling | Gazebo → AgenticROS → Nebius end-to-end |
| 3–9 ottobre | Loop di tool calling e allowlist | `look_around`, primo grafo semantico | Rotazione e stop cancellabile | Il modello richiede e ottiene una seconda vista |
| 10–16 ottobre | Belief, limite passi e gestione errori | Due stanze complete, replay offline | Porta: rilevamento, approccio e attraversamento | Disambiguazione attiva ripetibile |
| 17–23 ottobre | Integrazione completa e interfaccia demo | Test da pose iniziali differenti | `traverse_transition` con feedback | Cambio stanza deciso dal modello; feature freeze |
| 24–27 ottobre | Correzioni, README e setup pulito | Scenari di errore e misure | Stabilizzazione | Demo candidata e primo montaggio video |
| 28–30 ottobre | Solo correzioni bloccanti e submission | Registrazione finale | Supporto alle riprese | Repository pubblico, video e consegna |

## Ordine di lavoro immediato

1. Creare la chiave e identificare un modello NVIDIA che accetti immagini.
2. Avviare Gazebo e acquisire un frame tramite `ros2_camera_snapshot` di AgenticROS.
3. Inviare quel frame a Token Factory e validare la risposta.
4. Implementare in Rust un solo ciclo con due strumenti: `observe_place` e `look_around`.
5. Solo dopo il funzionamento del ciclo, costruire il mondo definitivo a due stanze.
6. Integrare le azioni Nav2 mapless quando il team mobilità le espone.

## Criteri di successo

La demo è pronta quando:

- usa realmente un modello NVIDIA su Nebius durante l'esecuzione;
- il modello riceve immagini generate dalla camera ROS della simulazione;
- il modello sceglie almeno un'azione attraverso AgenticROS;
- ogni azione richiesta viene validata localmente;
- il robot raccoglie nuova evidenza prima di decidere la propria stanza;
- il robot attraversa una transizione senza mappa metrica globale;
- un errore di rete o un timeout produce un arresto sicuro;
- il comportamento mostrato nel video è riproducibile dal repository pubblico.

## Rischi principali e riduzioni

| Rischio | Riduzione |
|---|---|
| Il modello NVIDIA disponibile non accetta immagini | Verifica nella Fase 0; separare temporaneamente grounding visivo e ragionamento mantenendo un modello NVIDIA sostanziale nel loop |
| Tool calling non affidabile | JSON Schema, allowlist e ciclo di correzione; mai interpretare testo libero come comando motorio |
| Immagini Gazebo poco leggibili | Oggetti grandi, luce controllata, viste note e immagini ridimensionate senza perdere dettagli |
| Integrazione Go2 troppo lunga | Validare prima il ciclo completo sull'AMR esistente, poi sostituire il modello robotico |
| Nav2 mapless non attraversa la porta | Testare presto una sola porta e usare un contratto locale indipendente dalla semantica |
| Latenza cloud elevata | Chiamate event-triggered, robot fermo durante il ragionamento e immagini compresse |
| Il modello continua a chiamare strumenti | Numero massimo di passi e stato terminale `insufficient_evidence` |
| La demo sembra semplice teleoperazione via LLM | Visualizzare in modo esplicito incertezza, evidenza cercata e cambiamento della decisione |

## Decisione sul Behavior Tree

Il compilatore e il Behavior Tree applicativo vengono rimossi dall'MVP. AgenticROS offre già capability e gestione delle missioni sufficienti per collegare il modello alle azioni, mentre il runtime Rust controlla il ciclo agente.

Il tema BT può essere ripreso dopo il feature freeze soltanto se la demo completa è già stabile. Non deve diventare una dipendenza per visione, ragionamento, disambiguazione o movimento mapless.




## Modelli
- Nemotron-Nano-V2-12b supporta immagini, ma richiede un endpoint dedicato.
- Nemotron-3-Nano-Omni non è disponibile sul tuo public endpoint.
I Nemotron accessibili con la tua chiave sono solo text-to-text.

- NVIDIA-Nemotron-3-Nano-30B-A3B è adatto a ragionamento e tool calling e costa circa $0.06 / 1M input e $0.24 / 1M output.