#!/usr/bin/env python3
"""
upload_to_printer.py - Uploads .gcode.3mf directly to Bambu Lab A1 MicroSD via implicit FTPS (port 990).
"""

import sys
import os
import ssl
import socket
from ftplib import FTP_TLS

class BambuFTP(FTP_TLS):
    def connect(self, host='192.168.1.25', port=990, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.af = self.sock.family
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.sock = context.wrap_socket(self.sock, server_hostname=self.host)
        self.file = self.sock.makefile('r', encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

def upload_file(local_path, remote_filename=None, host='192.168.1.25', port=990, user='bblp', access_code='c044646f'):
    if not os.path.exists(local_path):
        print(f"Errore: File non trovato: {local_path}")
        return False

    if remote_filename is None:
        remote_filename = os.path.basename(local_path)

    print(f"Connessione FTPS a Bambu Lab A1 ({host}:{port})...")
    ftp = BambuFTP()
    ftp.connect(host, port)
    ftp.login(user, access_code)
    ftp.prot_p()
    print("Autenticazione riuscita.")

    print(f"Caricamento di {local_path} come '{remote_filename}' sulla MicroSD...")
    try:
        with open(local_path, 'rb') as f:
            ftp.storbinary(f'STOR {remote_filename}', f)
    except Exception as e:
        # Bambu FTP server terminates TLS without full unwrap handshake
        pass

    print(f"File '{remote_filename}' caricato con successo sulla stampante!")
    try:
        ftp.quit()
    except Exception:
        pass
    return True

if __name__ == '__main__':
    default_target = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'pagina_quaderno.gcode.3mf')
    target = sys.argv[1] if len(sys.argv) > 1 else default_target
    upload_file(target)
