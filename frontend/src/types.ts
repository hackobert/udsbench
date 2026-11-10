/** Typen der API-Antworten (nur die von der UI genutzten Felder). */

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type Obj = Record<string, unknown>;

export interface ApiErrorDetail {
  loc?: string;
  msg?: string;
  type?: string;
  [key: string]: unknown;
}

export interface Subfunction {
  value: number;
  hex: string;
  name: string;
}

export interface ServiceParam {
  name: string;
  kind: string; // did | rid | byte | mask | u16 | u24 | dtc | alfid | hex
  description: string;
  optional: boolean;
  default: string | null;
}

export interface UdsService {
  sid: number;
  sid_hex: string;
  name: string;
  description: string;
  has_subfunction: boolean;
  sprm_allowed: boolean;
  subfunctions: Subfunction[];
  params: ServiceParam[];
  sub_params: Record<string, ServiceParam[]>;
  response_sid?: number;
}

export interface ServicesResponse {
  services: UdsService[];
  dtc_status_bits: string[];
}

export interface NrcEntry {
  code: number;
  hex: string;
  name: string;
  description: string;
}

export interface BitDef {
  name: string;
  bit: number;
  length: number;
  enum: Record<string, string> | null;
}

export interface ValueSpec {
  type: string; // uint | int | float | enum | bitfield | ascii | bcd | bytes | bool | hex …
  length: number | null;
  byteorder?: string;
  scale?: number;
  offset?: number;
  unit: string;
  enum: Record<string, string> | null;
  bits: BitDef[] | null;
  min: number | null;
  max: number | null;
  name?: string;
}

export interface DidDef extends ValueSpec {
  id: number;
  id_hex: string;
  name: string;
  description: string;
  access: string; // read | write | readwrite
  io_control: boolean;
}

export interface DtcDef {
  code: number;
  code_hex: string;
  display: string;
  name: string;
  description: string;
  severity: number | null;
}

export interface RoutineDef {
  id: number;
  id_hex: string;
  name: string;
  description: string;
  start_params: ValueSpec[];
  stop_params: ValueSpec[];
  result_fields: ValueSpec[];
  supports: string[];
}

export interface SessionDef {
  id: number;
  name: string;
}

export interface SecurityLevelDef {
  level: number;
  name: string;
  provider: string;
  params: Obj;
  session: number | null;
}

export interface EcuState {
  id: string;
  name: string;
  package: string;
  channel: string;
  tx_id: number;
  rx_id: number;
  functional_id: number | null;
  isotp_profile: string;
  session: number;
  session_name: string;
  unlocked_levels: number[];
  tester_present: { enabled: boolean; interval_ms: number; sent?: number };
  connected: boolean;
  sessions: SessionDef[];
  security_levels: SecurityLevelDef[];
  functional_group?: string | null;
  description?: string;
  transport_errors?: unknown[];
}

export interface ChannelStatus {
  name: string;
  backend: string;
  connected: boolean;
  connected_at?: number | null;
  tx: number;
  rx: number;
  tx_errors: number;
  adapter?: { state?: string; kind?: string; [key: string]: unknown };
  simulate?: boolean;
  error?: string | null;
}

export interface SimState {
  ecu: string;
  session: number;
  unlocked: number[];
  dids: Record<string, string>;
  dtcs: Record<string, string>;
  requests: number;
  [key: string]: unknown;
}

export interface ConnectionResponse {
  channels: ChannelStatus[];
  simulation: SimState[];
}

export interface Decoded {
  type?: string;
  text?: string;
  service?: string;
  nrc?: number;
  nrc_hex?: string;
  nrc_name?: string;
  nrc_description?: string;
  fields?: Obj;
  data?: string;
  [key: string]: unknown;
}

export interface UdsResult {
  cid?: string | null;
  ecu: string;
  functional: boolean;
  request: string;
  response: string | null;
  positive: boolean;
  negative: boolean;
  nrc: number | null;
  nrc_name: string | null;
  pending_count: number;
  suppress_positive: boolean;
  elapsed_ms: number | null;
  total_ms?: number | null;
  error: string | null;
  error_kind?: string | null;
  decoded: Decoded;
  responses: UdsResult[] | { ecu?: string; response: string; decoded?: Decoded; [key: string]: unknown }[];
  warnings: string[];
}

export interface Assertion {
  name: string;
  ok: boolean;
  message: string;
  expected: unknown;
  actual: unknown;
}

export interface StepRecord {
  name: string;
  action: string;
  depth: number;
  status: string;
  started?: number;
  duration_ms: number;
  ecu: string | null;
  request: string | null;
  response: string | null;
  elapsed_ms: number | null;
  nrc: number | null;
  decoded: Decoded;
  assertions: Assertion[];
  message: string;
  details?: Obj;
  attempt?: number;
}

export interface StepRunResponse {
  cid: string;
  step: StepRecord;
  result: UdsResult | null;
  vars: Obj;
}

export interface PreviewByte {
  value: string;
  role: string; // ae | pci | len | data | pad | fc
}

export interface PreviewFrame {
  can_id: number;
  can_id_hex: string;
  extended_id: boolean;
  fd: boolean;
  dlc: number;
  kind: string;
  note: string;
  bytes: PreviewByte[];
}

export interface Validation {
  ok: boolean;
  errors: string[];
  warnings: string[];
  suppress_positive?: boolean;
}

export interface PreviewResponse {
  payload: string;
  length: number;
  validation: Validation;
  description: string;
  profile: Obj;
  frames: PreviewFrame[];
  flow_control_expected: boolean;
}

export interface TraceFrame {
  kind: "frame";
  seq: number;
  ts: number;
  channel: string;
  dir: "tx" | "rx";
  id: number;
  id_hex: string;
  ext?: boolean;
  fd?: boolean;
  err?: boolean;
  dlc: number;
  len?: number;
  data: string;
  ascii: string;
  pci?: string | null;
  uds?: string | null;
  sid?: number | null;
  text?: string | null;
  ecu?: string | null;
  role?: string | null;
  cid?: string | null;
}

export interface TraceMessage {
  kind: "message";
  seq: number;
  ts: number;
  ts_end?: number;
  channel: string;
  dir: "tx" | "rx";
  id?: number;
  can_id?: number;
  frames: number;
  payload: string;
  len: number;
  uds?: string | null;
  sid?: number | null;
  text?: string | null;
  ecu?: string | null;
  role?: string | null;
}

export type TraceItem = TraceFrame | TraceMessage;

export interface TraceBatch {
  type: "batch";
  frames: TraceFrame[];
  messages: TraceMessage[];
  dropped: number;
}

export interface IsoTpProfile {
  name: string;
  description: string;
  channel: string;
  tx_id: number;
  rx_id: number;
  functional_id: number | null;
  extended_id: boolean;
  addressing: "normal" | "extended" | "mixed";
  tx_address_extension: number | null;
  rx_address_extension: number | null;
  functional_address_extension: number | null;
  block_size: number;
  st_min: number;
  st_min_tx_override: number | null;
  wft_max: number;
  padding: { enabled: boolean; byte: number };
  dlc_mode: "fixed" | "minimal";
  can_fd: boolean;
  fd_tx_dl: number;
  bitrate_switch: boolean;
  max_rx_length: number;
  timeouts: { n_as: number; n_ar: number; n_bs: number; n_cr: number };
  ecus?: string[];
  tx_dl?: number;
  st_min_text?: string;
}

export interface LibraryItem {
  id: string;
  name?: string;
  description?: string;
  package?: string | null;
  tags?: string[];
  ecu?: string | null;
  [key: string]: unknown;
}

export interface RunSummary {
  total: number;
  passed: number;
  failed: number;
  error: number;
  skipped: number;
}

export interface TestCaseResult {
  id: string;
  name: string;
  label: string;
  ecu: string | null;
  iteration: number;
  dataset: Obj;
  status: string;
  duration_ms: number;
  message: string;
  expected_result: string;
  steps: StepRecord[];
  log: unknown[];
}

export interface RunInfo {
  run_id: string;
  kind: string;
  target: string;
  name: string;
  status: string;
  created: number;
  started: number | null;
  finished: number | null;
  duration_ms: number;
  summary: RunSummary;
  planned: number;
  error: string | null;
  environment?: Obj;
  vars?: Obj;
  tests?: TestCaseResult[];
  suite_steps?: StepRecord[];
}

export interface PackageSummary {
  id: string;
  name: string;
  version: string;
  description: string;
  source: string | null;
  builtin: boolean;
  hash: string;
  active: boolean;
  counts: Record<string, number>;
}

export interface PackagesResponse {
  packages: PackageSummary[];
  active: string[];
  invalid: { path?: string; file?: string; error?: string; [key: string]: unknown }[];
}

export interface LogEntry {
  seq: number;
  ts: number;
  time: string;
  level: string;
  channel: string;
  logger: string;
  msg: string;
  cid: string | null;
  [key: string]: unknown;
}

export interface RecordingInfo {
  id: string;
  name: string;
  frames: number;
  started: number;
  size?: number;
  [key: string]: unknown;
}

export interface ReplayInfo {
  id: string;
  recording?: string;
  state?: string;
  mode?: string;
  sent?: number;
  total?: number;
  [key: string]: unknown;
}

export interface EventMsg {
  topic: string;
  ts?: number;
  [key: string]: unknown;
}
