export type JobRole = {
  id: number;
  code: string;
  name: string;
  department: string;
  description?: string | null;
  is_active: boolean;
};

export type Me = {
  id: number;
  username: string;
  display_name: string;
  email?: string | null;
  security_role: { id: number; code: string; name: string };
  permissions: string[];
  job_roles: JobRole[];
  must_change_password: boolean;
  session_idle_minutes: number;
};

export type DocumentVersion = {
  id: number;
  family_id: number;
  version_label: string;
  status: string;
  relative_path?: string;
  source_sha256: string;
  source_size: number;
  source_modified_at: string;
  change_summary: string;
  training_impact: string;
  training_impact_reason?: string | null;
  issue_date?: string | null;
  approved_at?: string | null;
  effective_at?: string | null;
  review_due_date?: string | null;
  superseded_at?: string | null;
  created_by: number;
  approved_by?: number | null;
  released_by?: number | null;
  created_at: string;
};

export type ControlledDocument = {
  id: number;
  code: string;
  title: string;
  document_type: string;
  owner_department: string;
  description?: string | null;
  review_interval_months: number;
  is_active: boolean;
  current_version?: DocumentVersion | null;
  forthcoming_version?: DocumentVersion | null;
  versions?: DocumentVersion[];
};

export type ControlledCopy = {
  id: number;
  document_version_id: number;
  copy_number: string;
  department: string;
  location: string;
  issued_to?: string | null;
  status: string;
  issued_at: string;
  issued_by: number;
  closed_at?: string | null;
  closure_reason?: string | null;
};

export type TrainingAssignment = {
  id: number;
  user_id: number;
  document_version_id: number;
  document_family_id: number;
  document_code: string;
  document_title: string;
  document_type: string;
  version_label: string;
  version_status: string;
  status: string;
  stored_status: string;
  requirement_type: string;
  assigned_at: string;
  due_at: string;
  completed_at?: string | null;
  closure_reason?: string | null;
  acknowledgement?: {
    acknowledged_at: string;
    statement: string;
    source_sha256: string;
    method: string;
  } | null;
};

export type Requirement = {
  id: number;
  job_role_id: number;
  job_role_code: string;
  job_role_name: string;
  document_family_id: number;
  document_code: string;
  document_title: string;
  requirement_type: string;
  due_days: number;
  is_active: boolean;
  reason: string;
  created_at: string;
};

export type ApiError = Error & { status?: number };
