# Synchronizace Google Kalendáře s Garminem

Google kalendář "VTP" je sdílený s dalšími lidmi (aby věděli, kdy je trénink),
takže ho nejde jen tak smazat celý a založit znovu. Když se skutečný rozvrh na
Garminu odchýlí od toho, co je v Google kalendáři (ruční přeházení termínů na
hodinkách/Connectu, posun týdnů apod.), je potřeba ho ručně přesynchronizovat.

Google Calendar `.ics` import needí existující události — jen přidává nové.
Proto je postup vždy: smazat staré → naimportovat čerstvé.

## Postup

### 1. Vygeneruj čerstvý export ze skutečného Garmin kalendáře

Windows terminál (potřebuje Garmin login, viz [CLAUDE.md](../CLAUDE.md)):

```
python push_plan.py --ics-garmin
```

Vytvoří `vtp-garmin.ics` — pozor, je to relativní cesta, zapíše se do adresáře,
ze kterého příkaz spouštíš (ne nutně tam, kde leží `push_plan.py`).

### 2. Smaž staré VTP události z Google kalendáře

Google Calendar nemá ve webovém/mobilním UI hromadný výběr + smazání pro výsledky
hledání. Použij **Google Apps Script** (script.google.com, pod vlastním Google
účtem — nic navíc se nepřipojuje, běží to jako makro nad tvým vlastním kalendářem).

Nejdřív najít/ověřit (jen čte, nic nemaže):

```javascript
function najdiVtpTreninky() {
  var kalendar = CalendarApp.getCalendarsByName('VTP')[0];
  var od = new Date('YYYY-MM-DD');        // dnešní datum
  var doDatumu = new Date('YYYY-MM-DD');  // konec plánu / rok dopředu
  var vsechny = kalendar.getEvents(od, doDatumu);
  var udalosti = vsechny.filter(function(u) {
    return u.getTitle().indexOf('VTP T') === 0;
  });
  Logger.log('Odpovídá: ' + udalosti.length);
  udalosti.forEach(function(u) {
    Logger.log(u.getStartTime() + ' — ' + u.getTitle());
  });
}
```

Zkontroluj v Logu (View → Logs), že počet a data sedí (jen budoucí VTP tréninky,
nic cizího). Teprve pak spusť mazací verzi:

```javascript
function smazVtpTreninky() {
  var kalendar = CalendarApp.getCalendarsByName('VTP')[0];
  var od = new Date('YYYY-MM-DD');
  var doDatumu = new Date('YYYY-MM-DD');
  var vsechny = kalendar.getEvents(od, doDatumu);
  var udalosti = vsechny.filter(function(u) {
    return u.getTitle().indexOf('VTP T') === 0;
  });
  udalosti.forEach(function(u) { u.deleteEvent(); });
  Logger.log('Smazáno: ' + udalosti.length);
}
```

Smazání jednotlivých událostí kalendář samotný ani jeho sdílení s ostatními
nijak neovlivní — maže se jen obsah, ne kalendář.

**Titulek má formát `VTP T{tyden:02d} {den} - {popis}`** (mezera za "VTP T", ne
pomlčka) — platí jak pro starý ruční `.ics` import, tak pro export z
`--ics-garmin` (`generate_ics_from_garmin()` v `push_plan.py`), takže filtr
`'VTP T'` zůstává platný i při dalších synchronizacích.

### 3. Naimportuj čerstvý `.ics` do stejného kalendáře

Google Calendar → ozubené kolo (Nastavení) → **Import a export** → vybrat
`vtp-garmin.ics` → v dropdownu "Přidat do kalendáře" zvolit **VTP** → Import.

## Poznámky

- `-h` / `--help` u `push_plan.py` funguje automaticky (argparse); samotné `?`
  ne — to je konvence Windows shellu, ne Pythonu.
