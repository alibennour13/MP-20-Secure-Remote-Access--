# MP-20 - Secure Remote Access

## Project

Secure remote administration of the MP-20 security robot.

## Security architecture

The supplier administration architecture is based on five security layers:

1. Perimeter protection
2. Encrypted VPN tunnel
3. Strong authentication
4. Role-Based Access Control
5. Traceability and monitoring

## Implemented technologies

- WireGuard
- OpenSSH
- UFW
- FreeRADIUS
- PAM
- TOTP / MFA
- Linux RBAC
- sudoers
- auditd
- journald
- Fail2Ban
- Wazuh

## Network architecture

- ens33: NAT / Internet access
- ens37: Host-only communication
- wg0: administration VPN

## Security principle

The supplier accesses the robot through the WireGuard VPN.

SSH is restricted to the WireGuard interface.

Authentication uses RADIUS and TOTP.

Authorization is controlled through RBAC.

Security events are monitored and logged.

## Secrets

Real credentials, private keys and authentication secrets are never stored in this repository.

Only anonymized `.example` configuration files are provided.
