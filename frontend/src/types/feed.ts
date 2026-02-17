/**
 * Typed feed metadata interfaces per evolution_feed_spec.md § 4.1
 */

export type AgentType = "watcher" | "architect" | "coder" | "patcher" | "system";
export type ProblemType = "starvation" | "overpopulation" | "low_diversity";
export type Severity = "low" | "medium" | "high" | "critical";
export type ChangeType = "new_trait" | "modify_trait" | "adjust_params";

export interface FeedTriggerMeta {
  readonly problem_type: ProblemType;
  readonly severity: Severity;
  readonly snapshot_tick?: number;
  readonly entity_count?: number;
  readonly avg_energy?: number;
  readonly dominant_trait?: string;
}

export interface FeedPlanMeta {
  readonly change_type: ChangeType;
  readonly target_class: string | null;
  readonly target_method: string | null;
  readonly description: string;
  readonly expected_outcome?: string;
  readonly constraints?: readonly string[];
}

export interface FeedMutationMeta {
  readonly mutation_id: string;
  readonly trait_name: string;
  readonly version: number;
  readonly file_path?: string;
}

export interface FeedCodeMeta {
  readonly snippet?: string;
  readonly validation_errors?: string | null;
}

export interface FeedRegistryMeta {
  readonly registry_version?: number;
  readonly rollback_to?: string | null;
}

export interface FeedMetadata {
  readonly cycle_id?: string;
  /** Версия схемы metadata. Всегда 1 в текущей реализации; нужен для будущих миграций. */
  readonly metadata_schema_version?: number;
  readonly trigger?: FeedTriggerMeta;
  readonly plan?: FeedPlanMeta;
  readonly mutation?: FeedMutationMeta;
  readonly code?: FeedCodeMeta;
  readonly registry?: FeedRegistryMeta;
  readonly [key: string]: unknown;
}

/**
 * Wire-формат: то, что приходит по WebSocket напрямую из backend.
 * Поля `id` и `type` отсутствуют — они не передаются сервером.
 */
export interface FeedMessageWire {
  readonly agent: AgentType | string;
  readonly action: string;
  readonly message: string;
  readonly timestamp: number; // Unix seconds (float)
  readonly metadata?: FeedMetadata;
}

/**
 * Нормализованный формат: хранится в Zustand store.
 * `id` генерируется на клиенте хуком useFeedStream (авто-инкремент).
 */
export interface FeedMessage {
  readonly id: number;
  readonly agent: AgentType | string;
  readonly action: string;
  readonly message: string;
  readonly timestamp: number; // Unix seconds (number, не string)
  readonly metadata?: FeedMetadata;
}
