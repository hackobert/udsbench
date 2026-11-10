/** Gemeinsamer Anwendungszustand (ECUs, Kataloge, Verbindung) – Daten kommen ausschließlich aus der API. */
import type { ApiClient } from "./api";
import { Emitter } from "./emitter";
import * as storage from "./storage";
import type {
  ConnectionResponse,
  DidDef,
  DtcDef,
  EcuState,
  EventMsg,
  NrcEntry,
  RoutineDef,
  ServicesResponse,
  UdsService,
} from "./types";
import type { WsState } from "./ws";

export type StoreKey = "ecus" | "catalogs" | "connection" | "selectedEcu" | "eventsState";

export class Store {
  ecus: EcuState[] = [];
  selectedEcu: string | null = storage.load<string | null>("ecu", null);
  services: UdsService[] = [];
  dtcStatusBits: string[] = [];
  dids: DidDef[] = [];
  dtcs: DtcDef[] = [];
  routines: RoutineDef[] = [];
  nrc: NrcEntry[] = [];
  connection: ConnectionResponse = { channels: [], simulation: [] };
  eventsState: WsState = "closed";
  /** Vorbelegung für die Reports-View (aus Trace-/Timechart-Auswahl). */
  reportRange: { from: number; to: number } | null = null;
  readonly changed = new Emitter<StoreKey>();
  readonly events = new Emitter<EventMsg>();

  constructor(private readonly api: ApiClient) {}

  ecu(id?: string | null): EcuState | undefined {
    const key = id ?? this.selectedEcu;
    return this.ecus.find((e) => e.id === key);
  }

  service(sid: number): UdsService | undefined {
    return this.services.find((s) => s.sid === sid);
  }

  selectEcu(id: string | null): void {
    this.selectedEcu = id;
    storage.save("ecu", id);
    this.changed.emit("selectedEcu");
  }

  /** Abo auf ein Event-Topic. */
  on(topic: string, fn: (e: EventMsg) => void): () => void {
    return this.events.on((e) => {
      if (e.topic === topic || topic === "*") fn(e);
    });
  }

  async refreshEcus(): Promise<void> {
    this.ecus = await this.api.get<EcuState[]>("/ecus");
    if (!this.ecus.some((e) => e.id === this.selectedEcu)) {
      this.selectedEcu = this.ecus[0]?.id ?? null;
    }
    this.changed.emit("ecus");
  }

  async refreshConnection(): Promise<void> {
    this.connection = await this.api.get<ConnectionResponse>("/connection");
    this.changed.emit("connection");
  }

  async refreshCatalogs(): Promise<void> {
    const [svc, dids, dtcs, routines, nrc] = await Promise.all([
      this.api.get<ServicesResponse>("/uds/services"),
      this.api.get<DidDef[]>("/catalogs/dids"),
      this.api.get<DtcDef[]>("/catalogs/dtcs"),
      this.api.get<RoutineDef[]>("/catalogs/routines"),
      this.api.get<NrcEntry[]>("/uds/nrc"),
    ]);
    this.services = svc.services;
    this.dtcStatusBits = svc.dtc_status_bits;
    this.dids = dids;
    this.dtcs = dtcs;
    this.routines = routines;
    this.nrc = nrc;
    this.changed.emit("catalogs");
  }

  async refreshAll(): Promise<void> {
    await Promise.all([this.refreshEcus(), this.refreshConnection(), this.refreshCatalogs()]);
  }
}
