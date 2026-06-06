This is an HTB CTF Fullpwn or machine-style challenge.

You may enumerate the provided machine IP only (see TARGET CONTEXT / target.json).
A VPN connection to HTB is usually required; assume it is already connected.

Prioritize, in order:
- service discovery (nmap -Pn -sV --top-ports 100 <IP>, then targeted full scans)
- web enumeration (directories, vhosts, parameters) when web ports are open
- credential discovery
- initial foothold
- privilege escalation
- user/root or challenge flag discovery (HTB{...} / CHTB{...})

Always maintain a clear attack-path log in notes.md.
Avoid destructive actions. Use parallel=1 expectations: this target is stateful.
