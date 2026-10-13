IMAANAA MICROFINANCE - GitHub / Render / Neon

Faayiloota:
- app.py: koodii guutuu appii
- requirements.txt: packages Python
- render.yaml: Render deployment settings

Deploy:
1. Faayiloota kana hunda repository GitHub haaraa ykn kan appii kee keessatti olkaa'i.
2. Render -> New -> Web Service -> repository filadhu. Yoo render.yaml argame settings isaa hordofi.
3. Render Environment keessatti DATABASE_URL jechuun Neon PostgreSQL connection string kee galchi. Neon dashboard irraa connection string pooled (pooler) fudhachuu dandeessa; password sirrii qabaachuu qaba.
4. SECRET_KEY Render'n render.yaml keessatti ofumaan uuma; yoo render.yaml hin fayyadamne, Environment keessatti SECRET_KEY dheeraa fi iccitii ta'e uumi.
5. Deploy erga xumuramee booda URL Render kee bani.

DB:
Appiin yeroo jalqaba DATABASE_URL argatu init_db() dhaan tabeloota barbaachisan uuma. DATABASE_URL hin galchine yoo ta'e appiin hin ka'u.

Login jalqabaa (users table duwwaa ta'ee yeroo jalqaba qofa):
- CEO: ceo / ceo999
- Manager: manager1 / manager123
- Maker: maker1 / maker123
- Auditor: auditor1 / auditor123
- Loan officer: officer1 / officer123
- External agent: ext_agent1 / agent123

Nageenya:
Deploy erga gootee booda password jalqabaa jijjiiri. Password jalqabaa koodii duraanii keessaa dhufe; feature biraa hin jijjiirne.

Faayiloota suuraa/ID:
Koodiin kun faayiloota uploads/ keessatti tursiisa. Free Render filesystem yeroo deploy/restart ta'u qulqullaa'uu danda'a; kanaaf suuraa/ID yeroo dheeraaf eeguu barbaadde, Render persistent disk (plan deeggaru irratti) ykn object storage itti dabaluun barbaachisa. Neon database'n odeeffannoo fi maqaa faayila tursiisa, garuu faayila suuraa mataa isaa Neon keessa hin kaa'u.

Fooyya'iinsa ajajame:
- Suuraa maammilaa fi National ID bakka maammilli itti ilaalamu irratti link/view dabalame (customer list, statement, edit, pending review, transaction approval, maker verification).
- Search customer list: maqaa, account ID, bilbila, account type fi status irratti barbaada.
- Route/feature baankii duraanii hafan hin haqune; koodii syntax-check qofa darbeera, live Neon/Render deploy irratti hin mirkanoofne.
