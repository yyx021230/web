import api from './api';

export interface MasterAccount {
  id: number;
  xhs_account_id: string;
  account_name: string;
  owner_user_id: number | null;
  owner_name: string | null;
  department: string;
  account_type: string;
  status: string;
  revision: number;
  profile_url?: string | null;
  homepage_sync_eligible?: boolean;
}

export interface MasterPreview {
  preview_id: string;
  source_hash: string;
  source_url: string;
  expires_at: string;
  rows: Array<{
    row: number;
    xhs_account_id: string;
    account_name: string;
    owner_user_id: number | null;
    owner_name: string | null;
    department: string;
    status: string;
    operation: string;
    warnings: string[];
    changed_fields: string[];
    history_notes: number;
    confirmed_old_id: string | null;
  }>;
  skipped: Array<{ row: number; reason: string }>;
  unlisted_accounts: Array<{ id: number; xhs_account_id: string; account_name: string;
    references: Record<string, number>; action: 'delete_empty' | 'archive_history' }>;
}

export interface MasterApplyResult {
  created: number;
  updated: number;
  selected: number;
  history_notes_moved: number;
  unlisted_accounts_deleted: number;
  unlisted_accounts_archived: number;
  history_conflicts: Array<{ note_id: number; account_id: number; reason: string }>;
}

export interface MasterApplyRequest {
  source_hash: string;
  rows: number[];
  include_history: boolean;
  replace_all: boolean;
}

export const xhsAccountMasterApi = {
  async profile(account: MasterAccount, profile_url: string) {
    return (await api.patch(`/admin/xhs/account-master/accounts/${account.id}/profile`, {
      profile_url, expected_revision: account.revision,
    })).data;
  },
  async accounts() {
    return (await api.get<MasterAccount[]>('/xhs/accounts')).data;
  },
  async preview(file: File) {
    const form = new FormData();
    form.append('file', file);
    return (await api.post<MasterPreview>('/admin/xhs/account-master/previews', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })).data;
  },
  async apply(previewId: string, body: MasterApplyRequest) {
    return (await api.post<MasterApplyResult>(`/admin/xhs/account-master/previews/${previewId}/apply`, body)).data;
  },
};
