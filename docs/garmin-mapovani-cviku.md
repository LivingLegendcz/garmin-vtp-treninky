# Mapování cviků: VTP plán → Garmin exercise keys

Pozor: klíče jsou kvalifikovaný odhad podle známé Garmin exercise taxonomie. Před generováním silových tréninků ověřit proti aktuálnímu seznamu z Garmin API (viz implementační plán, krok 2). Formát Garmin: `category` + `exerciseName`.

| Český název (plán) | Garmin kategorie | Garmin exercise key (odhad) | Poznámka |
|---|---|---|---|
| klik | PUSH_UP | PUSH_UP | |
| klik na kolenou | PUSH_UP | KNEELING_PUSH_UP | |
| negativní klik | PUSH_UP | PUSH_UP | jen excentrická fáze — do poznámky kroku |
| klik diamant (úzký) | PUSH_UP | DIAMOND_PUSH_UP | |
| klik široký | PUSH_UP | WIDE_GRIP_PUSH_UP | příp. PUSH_UP + poznámka |
| klik s tlesknutím | PUSH_UP | CLAPPING_PUSH_UP / PLYO_PUSH_UP | |
| klik do lehu se zvednutím dlaní | PUSH_UP | HAND_RELEASE_PUSH_UP | |
| leh-sed | SIT_UP | SIT_UP | |
| sklapovačky | SIT_UP | V_UP | |
| jízda na kole (lokty ke kolenům) | CRUNCH | BICYCLE_CRUNCH | |
| rotace trupu v sedu | CORE | RUSSIAN_TWIST | |
| nůžky / střih nohama vleže | CORE | FLUTTER_KICK | příp. SCISSOR_KICK |
| přednožování vleže (dotyk špiček) | CRUNCH | TOE_TOUCH | |
| plank / vzpor ležmo výdrž | PLANK | PLANK | časový krok |
| plank na boku | PLANK | SIDE_PLANK | |
| extenze v zádech (leh na břiše) | HYPEREXTENSION | SUPERMAN / BACK_EXTENSION | |
| dřep | SQUAT | BODY_WEIGHT_SQUAT | |
| dřep do výponu | SQUAT | SQUAT_TO_CALF_RAISE | příp. SQUAT + poznámka |
| dřep s výskokem / výskok z podřepu | PLYO | JUMP_SQUAT | |
| výpad | LUNGE | LUNGE | |
| chůze do výpadu | LUNGE | WALKING_LUNGE | |
| žabáky | PLYO | FROG_JUMP / BROAD_JUMP | |
| výskok na bednu | PLYO | BOX_JUMP | výška 30–50 cm do poznámky |
| angličák | TOTAL_BODY | BURPEE | |
| poskoky „panák" | CARDIO | JUMPING_JACKS | |
| veslování vsedě (imitace bez zátěže) | ROW | SEATED_ROW | bez zátěže — do poznámky |
| shyb | PULL_UP | PULL_UP | |
| negativní shyb | PULL_UP | NEGATIVE_PULL_UP | příp. PULL_UP + poznámka „3 s brzdit" |
| vis na hrazdě | PULL_UP | DEAD_HANG / BAR_HANG | časový krok |
| vis + přitahování kolen | CORE | HANGING_KNEE_RAISE | |
| výdrž v podřepu | SQUAT | WALL_SIT / SQUAT_HOLD | časový krok |

## Běžecké pojmy

| Pojem | Převod do Garmin kroku |
|---|---|
| rozklusání / rozklus | warmup, time, bez cíle nebo Z1–Z2 |
| výklus | cooldown, time |
| indiánský běh | repeat: chůze X s + běh Y s |
| souvislý běh na X % SFmax | interval, time, HR target (% max) |
| fartlek R/V | repeat bloky: rychlejší běh / volný klus, časové kroky |
| běžecká ABECEDA | součást warmup — poznámka kroku, nestrukturovat |
| tempo X:XX/km | interval, distance, pace target |
| pauza do poklesu SF na 120 | rest krok ukončený lap tlačítkem + poznámka |
