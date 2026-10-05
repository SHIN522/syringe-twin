"""Current-run SQLite historian; each backend launch owns a separate database."""
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
from uuid import uuid4


class Historian:
    def __init__(self, directory='data'):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"twin_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}.db"
        self.commands_written = 0
        self.events_written = set()
        self.known_parts = {}
        self._schema()

    def _schema(self):
        with sqlite3.connect(self.path) as con:
            con.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE parts(serial TEXT PRIMARY KEY,t_in REAL,t_out REAL,status TEXT,reject_codes TEXT,meas_json TEXT);
            CREATE TABLE part_events(serial TEXT,t REAL,station TEXT,event TEXT,data_json TEXT);
            CREATE TABLE alarms(code TEXT,station TEXT,sev TEXT,t_raised REAL,t_cleared REAL);
            CREATE TABLE commands(t REAL,wall TEXT,user TEXT,cmd TEXT,args_json TEXT);
            CREATE TABLE kpi_samples(t REAL,json TEXT);
            CREATE TABLE state_log(station TEXT,t REAL,state TEXT,reason TEXT);
            ''')

    def write(self, s, payload):
        with sqlite3.connect(self.path) as con:
            for p in s.parts.values():
                row = (p.serial,p.t_in,p.t_out,p.status,json.dumps(p.reject_codes),json.dumps(p.meas))
                if self.known_parts.get(p.serial) != row:
                    con.execute('INSERT OR REPLACE INTO parts VALUES(?,?,?,?,?,?)', row)
                    self.known_parts[p.serial] = row
                for ev in p.events:
                    text = json.dumps(ev, sort_keys=True)
                    key = (p.serial,text)
                    if key not in self.events_written:
                        con.execute('INSERT INTO part_events VALUES(?,?,?,?,?)',
                                    (p.serial,ev['t'],ev['station'],ev.get('event',''),text))
                        self.events_written.add(key)
            for row in s.commands[self.commands_written:]:
                con.execute('INSERT INTO commands VALUES(?,?,?,?,?)',
                            (row['t'],row['wall'],row['user'],row['cmd'],json.dumps(row['args'])))
            self.commands_written = len(s.commands)
            con.execute('DELETE FROM alarms')
            con.executemany('INSERT INTO alarms VALUES(?,?,?,?,?)',
                            [(a['code'],a['station'],a['sev'],a['t_raised'],a['t_cleared']) for a in s.alarms])
            con.execute('INSERT INTO kpi_samples VALUES(?,?)', (s.t,json.dumps(payload['kpi'])))
            con.executemany('INSERT INTO state_log VALUES(?,?,?,?)',
                            [(n,s.t,st.state,st.reason) for n,st in s.stations.items()])
