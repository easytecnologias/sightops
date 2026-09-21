FROM alpine:3.20
# Ferramentas de rede pro provisionador (wg, ip, iptables) + python.
RUN apk add --no-cache python3 iproute2 wireguard-tools iptables
COPY iso_provisioner.py /app/iso_provisioner.py
ENTRYPOINT ["python3", "/app/iso_provisioner.py"]
