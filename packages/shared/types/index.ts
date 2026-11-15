/**
 * Shared types for transversal project apps.
 * Extend with domain types (e.g. Location, Sale, Customer) as needed.
 */

// Example placeholder — replace with your domain types
export type Id = string;

export interface BaseEntity {
  id: Id;
  createdAt?: string;
  updatedAt?: string;
}

export type IncidentCategory =
  | "RETURN_REQUEST"
  | "DAMAGE"
  | "DELAYED_DELIVERY"
  | "WRONG_ADDRESS"
  | "LOST_PARCEL";

export type IncidentStatus =
  | "open"
  | "in_progress"
  | "resolved"
  | "discarded";

export type IncidentOrigin = "customer" | "branch" | "internal";
export type IncidentBranch = "Los Angeles" | "Zaragoza" | "central";

export interface Incident extends BaseEntity {
  title: string;
  description: string;
  category: IncidentCategory;
  status: IncidentStatus;
  origin: IncidentOrigin;
  branch: IncidentBranch;
}

export interface IncidentSummary {
  total: number;
  by_status: Record<IncidentStatus, number>;
  by_category: Record<IncidentCategory, number>;
  by_origin: Record<IncidentOrigin, number>;
  by_branch: Record<IncidentBranch, number>;
}
