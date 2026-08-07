import ldap3
import random
import os
import sys

# Add backend to path so imports work when running from command line
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from backend.config import settings

def seed_samba():
    server = ldap3.Server(settings.ldap_server)
    conn = ldap3.Connection(
        server, 
        user=settings.ldap_bind_dn, 
        password=settings.ldap_bind_password, 
        auto_bind=True
    )
    
    print("Connected to Samba AD.")
    
    base_dn = settings.ldap_base_dn
    ous = ["IT", "HR", "Engineering", "Finance", "Sales"]
    
    # 1. Create OUs
    for ou in ous:
        ou_dn = f"OU={ou},{base_dn}"
        try:
            conn.add(ou_dn, attributes={'objectClass': ['top', 'organizationalUnit']})
            print(f"Created OU: {ou_dn}")
        except Exception as e:
            print(f"OU {ou_dn} might already exist: {e}")

    # 2. Create Computer Objects
    os_options = ["Windows 10 Pro", "Windows 11 Enterprise", "Windows Server 2022"]
    
    count = 0
    for i in range(50):
        ou = random.choice(ous)
        ou_dn = f"OU={ou},{base_dn}"
        hostname = f"WS-{ou[:3].upper()}-{str(i).zfill(3)}"
        dn = f"CN={hostname},{ou_dn}"
        
        attrs = {
            'objectClass': ['top', 'person', 'organizationalPerson', 'user', 'computer'],
            'sAMAccountName': f"{hostname}$",
            'userAccountControl': 4096, # WORKSTATION_TRUST_ACCOUNT
            'operatingSystem': random.choice(os_options),
            'dNSHostName': f"{hostname}.testlab.local"
        }
        
        try:
            if conn.add(dn, attributes=attrs):
                count += 1
                if count % 10 == 0:
                    print(f"Created {count} computers...")
            else:
                print(f"Failed to create {hostname}: {conn.result}")
        except Exception as e:
            print(f"Error creating {hostname}: {e}")
            
    print(f"Samba AD Seed Complete. Created {count} computers.")
    conn.unbind()

if __name__ == "__main__":
    seed_samba()
