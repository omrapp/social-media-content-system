export interface Notification {
  id: string;
  type: "error" | "success" | "warning" | "info";
  title: string;
  message?: string;
  read: boolean;
  created_at: string;
}

export interface TokenStatus {
  status: string;
  days_left?: number;
  expires_at?: string;
  message?: string;
}
