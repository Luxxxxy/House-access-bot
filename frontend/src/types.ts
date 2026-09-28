export type Role = 'ADMIN' | 'GUARD' | 'RESIDENT' | 'UNREGISTERED';

export interface Apartment {
  id: string;
  number: string;
  building: string;
  complex_id?: string;
  complex_name?: string;
}

export interface UserProfile {
  user_id: number;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  default_contact?: string | null;
  apartments: Apartment[];
  guard_status?: string | null;
  guard_checkpoints: { id: string; name: string }[];
  admin_complexes: { id: string; name: string }[];
  demo: boolean;
}

export interface Visit {
  id: string;
  resident_id: number;
  resident_name: string;
  apartment_id: string;
  apartment: string;
  building: string;
  checkpoint_id: string;
  checkpoint: string;
  visitor_type: 'COURIER' | 'GUEST' | 'REPAIR' | 'OTHER';
  visitor_name: string;
  visitor_car_number?: string | null;
  resident_contact: string;
  estimated_arrival_at?: string | null;
  comment?: string | null;
  status: string;
  is_pinned: boolean;
  created_at: string;
  resolved_at?: string | null;
  rejection_reason?: string | null;
  notified_guards?: number;
}

export interface ApiError extends Error {
  status?: number;
}

export interface AuthContext {
  authorization?: string;
  demoUserId?: number;
}
