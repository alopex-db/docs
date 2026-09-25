# Chirps Connectivity Layer

**Status**: Planned  
**Target**: Chirps v0.7-v0.9  
**Last updated**: 2026-09-25

## 1. 目的

Chirps に transport より下位、membership / messaging より手前の **Connectivity Layer** を明示的に導入する。

現在の Chirps は persistent `NodeId`、QUIC/TLS、SWIM、QoS、Raft、File Transfer を持つ一方、bootstrap / reconnect の一部は `SocketAddr` を直接扱う。Federation / Multi-Cluster では、NAT、CGNAT、IPv4/IPv6、relay、endpoint change を跨いでも同一 peer として接続を維持する必要がある。

基本原則は次の通り。

```text
identity != endpoint != path != connection
```

- **Identity**: 長寿命の logical peer identity。Chirps では persistent `NodeId` を中心にする。
- **Endpoint**: ある時点で観測された到達候補。LAN / public / NAT-mapped / relay 等。
- **Path**: 2 peer 間で実際に利用可能な経路。
- **Connection**: 選択された path 上の QUIC session。

QUIC/TLS は維持し、WireGuard を QUIC の下へ追加しない。

## 2. 現行との境界

現行の `chirps-transport-quic` は QUIC session、flow control、priority、QoS、retransmission、handshake を担当する。

Connectivity Layer はその前段で、

1. peer identity から endpoint candidate を得る
2. direct path を試す
3. 必要なら NAT traversal を行う
4. direct 不可なら relay を選ぶ
5. 利用可能 path を transport に渡す

責務を持つ。

```text
Chirps Mesh / SWIM / Raft / File Transfer
                  |
          MessageProfile / QoS
                  |
           QUIC Transport
                  |
          Connectivity Layer
        /          |           \
   Direct       NAT path       Relay
        \          |           /
                 UDP/IP
```

## 3. Identity と location

`NodeId` を network location から独立させる。

概念モデル:

```rust
pub struct PeerConnectivity {
    pub node_id: NodeId,
    pub endpoints: EndpointSet,
    pub active_path: Option<PathId>,
}

pub struct EndpointSet {
    pub candidates: Vec<EndpointCandidate>,
}

pub struct EndpointCandidate {
    pub endpoint: Endpoint,
    pub source: EndpointSource,
    pub observed_at: Instant,
    pub expires_at: Option<Instant>,
}

pub enum Endpoint {
    Direct(SocketAddr),
    Discovered(SocketAddr),
    NatMapped(SocketAddr),
    Relay(RelayEndpoint),
}
```

上記は設計上の概念形であり、公開APIをこの形に固定するものではない。

## 4. Endpoint discovery / rendezvous

固定 seed は bootstrap 手段として維持する。ただし、seed address を peer identity と同一視しない。

v0.8 では以下を追加する。

- local/private endpoint candidate の収集
- externally observed endpoint の登録
- authenticated peer 間での candidate exchange
- freshness / expiry
- IPv4 / IPv6 candidate
- pluggable rendezvous provider

Rendezvous は membership authority ではなく、接続候補交換の補助サービスとする。

## 5. NAT traversal

Chirps は QUIC/TLS を application transport として維持し、UDP path の確立のみを Connectivity Layer が補助する。

対象:

- external address discovery
- simultaneous UDP probing
- hole punching
- NAT rebinding
- candidate validation
- failure classification

NAT traversal の失敗は relay fallback へ渡せる明示的状態にする。

## 6. Relay fallback

Direct path が成立しない場合のみ relay を利用する。

Relay の責務:

- authenticated relay session
- cluster isolation
- connection / bandwidth / queue ceiling
- direct path recovery の観測
- relay usage metrics

Relay は peer identity、membership、authorization の authority にならない。mTLS / NodeId の trust model は relay 経由でも維持する。

## 7. Path Manager

v0.9 では同一 peer に対する複数 path を継続評価する。

候補例:

- LAN direct
- WAN direct
- NAT-traversed
- relay

観測値:

- RTT
- packet loss
- effective bandwidth
- stability
- relay / direct
- failure history

Path switch で peer identity や application-level delivery semantics を変えない。

## 8. MessageProfile × PathPolicy

Chirps 既存の MessageProfile / QoS を connectivity と接続する。

初期方針:

| Traffic | Path policy |
|---|---|
| Control / Raft | lowest-latency direct preferred、relay allowed |
| Gossip / Ephemeral | any viable path、過負荷時 drop を許可 |
| Snapshot | direct strongly preferred、relay は明示許可 + bandwidth cap |
| File Transfer | direct preferred、relay optional |
| Durable | delivery guarantee は backend が保持し、path change と分離 |

Path selection は delivery semantics を暗黙に変更してはならない。

## 9. Version allocation

### v0.7

**Connectivity abstraction**

- Node identity と network location の分離
- EndpointSet / PathCandidate を追加可能な transport boundary
- static seed bootstrap の後方互換
- Issue: https://github.com/alopex-db/alopex-chirps/issues/78

### v0.8

**Federation connectivity**

- endpoint discovery / rendezvous
- UDP NAT traversal
- relay fallback
- mixed-version / TLS rotation / churn 検証

Issues:

- https://github.com/alopex-db/alopex-chirps/issues/79
- https://github.com/alopex-db/alopex-chirps/issues/80
- https://github.com/alopex-db/alopex-chirps/issues/81
- https://github.com/alopex-db/alopex-chirps/issues/10
- https://github.com/alopex-db/alopex-chirps/issues/11

### v0.9

**Multi-Cluster Connectivity**

- Path Manager
- path health / selection / recovery
- MessageProfile × PathPolicy
- cross-cluster HLC / TSO integration

Issues:

- https://github.com/alopex-db/alopex-chirps/issues/82
- https://github.com/alopex-db/alopex-chirps/issues/83

HLC 自体は Chirps v0.6 で実装済みであり、v0.9 で新規実装する対象ではない。

## 10. Capability negotiation

既存 handshake capability と #74 の versioned capability advertisement を利用し、connectivity capability を versioned に表現する。

候補:

- endpoint discovery
- NAT traversal
- relay
- path migration

Capability advertisement は機能の有無を表現するものであり、connectivity 実装そのものは #79-#83 で追跡する。

## 11. Federation との関係

Alopex DB の Federation Gateway は remote cluster を単一 `SocketAddr` / 単一 `QuicConnection` として保持しない。

```text
ClusterId
   |
Remote cluster identity
   |
Peer/EndpointSet
   |
Path Manager
   |
Selected connectivity path
   |
QUIC
```

Alopex DB は replication / conflict resolution / global routing を担当し、direct/relay/NAT といった physical connectivity は Chirps に委譲する。

## 12. 参考実装

参考にする対象と採用範囲を分離する。

- **Tailscale Tailcat / magicsock**: identity-location 分離、endpoint discovery、NAT traversal、direct/relay transition
- **Tailscale DERP**: rendezvous / relay の operational model
- **iroh**: identity-oriented endpoint、direct/relay connectivity
- **rust-libp2p**: PeerId / address separation、AutoNAT、circuit relay
- **WebRTC ICE/STUN**: candidate gathering / connectivity checks

Tailcat の WireGuard / userspace TCP stack / netcat API は Chirps の採用対象ではない。Chirps は QUIC-native transport を維持する。

## 13. 非目標

- Tailscale / DERP へのサービス依存
- WireGuard の導入
- VPN / tailnet 相当の構築
- connectivity layer に membership authority を持たせる
- relay に application authorization を委譲する
