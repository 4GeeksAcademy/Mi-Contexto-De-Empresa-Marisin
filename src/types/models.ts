// src/types/models.ts

export type WarehouseLocation = 'Los Angeles' | 'Zaragoza';
export type ShipmentStatus = 'In Transit' | 'Delivered' | 'Failed' | 'Pending';
export type ReturnStatus = 'Pending Approval' | 'Approved' | 'Rejected' | 'Collected' | 'Inspected';
export type ItemCondition = 'Like New' | 'Damaged' | 'Defective' | 'Unsalvageable';
export type TicketPriority = 'Low' | 'Medium' | 'High' | 'Critical';
export type SentimentAnalysis = 'Positive' | 'Neutral' | 'Negative';

export interface SKUInventory {
    sku: string;
    productName: string;
    clientBrand: string;
    stockLA: number;
    stockZaragoza: number;
    minRequiredStock: number; // Para alertas de stock bajo
}

export interface CarrierShipment {
    id: string;
    trackingNumber: string;
    carrierName: 'UPS' | 'FedEx' | 'DHL' | 'MRW' | 'SEUR' | 'Local';
    origin: WarehouseLocation;
    destinationCountry: string;
    weightKg: number;
    urgency: 'Standard' | 'Express';
    status: ShipmentStatus;
    deliveryTimeDays?: number; // Para KPI de entrega a tiempo
    costEuro: number;
    hasIncident: boolean;
}

export interface OrderReturn {
    id: string;
    shipmentId: string;
    clientBrand: string;
    reason: string;
    status: ReturnStatus;
    estimatedValueEuro: number;
    aiInspectionCondition?: ItemCondition; // Clasificado por la IA de fotos
    requiresHumanReview: boolean;
}

export interface CustomerTicket {
    id: string;
    clientBrand?: string; // Si es B2B viene la marca, si es B2C queda opcional
    consumerEmail?: string;
    channel: 'Email' | 'WhatsApp' | 'Phone';
    subject: string;
    sentiment: SentimentAnalysis;
    isResolved: boolean;
    createdAt: Date;
}

export interface BrandClient {
    id: string;
    companyName: string;
    contractExpirationDate: Date;
    monthlyVolumeEuro: number;
    renewalRiskScore: number; // 0 a 100 (Salud del cliente)
}