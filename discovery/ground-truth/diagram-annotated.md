Client -> API Gateway (HTTPS)
API Gateway -> Auth Service (validate token)
Auth Service -> User DB (lookup)
API Gateway -> Task Service (gRPC)
Task Service -> Redis Cache (read/write)

All services behind Wireguard — no public exposure
