// types/index.ts

export type CandidateStatus = string;
export type CandidateStage = string;

export interface Candidate {
  id: number | string;
  name: string;
  email: string;
  phone?: string;
  position: string;
  linkedin?: string;
  cv_url?: string;
  years_of_experience?: number;
  status: CandidateStatus;
  stage: CandidateStage;
  applied_at?: string;
  created_at?: string;
}

export interface Note {
  id: number | string;
  record_id: number | string;
  content: string;
  created_at?: string;
}

export interface CandidateFormData {
  name: string;
  email: string;
  phone?: string;
  position: string;
  linkedin?: string;
  cv_url?: string;
  years_of_experience?: number;
  status: CandidateStatus;
  stage: CandidateStage;
}