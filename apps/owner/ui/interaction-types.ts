export type InteractionKind =
  | "model_select"
  | "reasoning_select"
  | "usage_select"
  | "permissions_select"
  | "resume_directory"
  | "workspace_trust"
  | "approval"
  | "generic_tui";

export type InteractionAction = "previous" | "next" | "choose" | "cancel";

export interface InteractionOption {
  id: string;
  label: string;
  description: string;
  selected: boolean;
  current: boolean;
  disabled: boolean;
}

export interface InteractionQuestion {
  id: string;
  header: string;
  question: string;
  options: Array<{ label: string; description: string }>;
  isOther: boolean;
  isSecret: boolean;
}

export interface PendingInteraction {
  id: string;
  generation: number;
  kind: InteractionKind | string;
  title: string;
  prompt: string;
  options: InteractionOption[];
  questions?: InteractionQuestion[];
  details?: Record<string, unknown>;
  responseKind?: "choice" | "questions";
  actions: InteractionAction[];
  source: "codex-tui" | string;
  status: "pending";
}

export interface InteractionResponse {
  interaction: PendingInteraction | null;
  changed?: boolean;
  resolved?: boolean;
  ignored?: boolean;
}

export interface InteractionHostOptions {
  onRespond(request: {
    interactionId: string;
    action?: InteractionAction;
    optionId?: string;
    answers?: Record<string, string[]>;
  }): Promise<InteractionResponse>;
  onError?(error: unknown): void;
}

export interface InteractionHostController {
  update(interaction: PendingInteraction | null): void;
  confirmCommand(values: {
    command: string;
    description: string;
    risk: string;
  }): Promise<boolean>;
  destroy(): void;
}
