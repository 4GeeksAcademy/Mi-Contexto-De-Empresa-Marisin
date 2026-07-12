// src/utils/transformations.ts

import { SKUInventory, CarrierShipment, OrderReturn, CustomerTicket } from '../types/models';

/**
 * Interfaces explícitas para la estructura de los reportes
 */
export interface WarehouseStockReport {
    totalSKUs: number;
    totalStockLA: number;
    totalStockZaragoza: number;
    globalTotalStock: number;
}

export interface CarrierPerformanceReport {
    totalShipments: number;
    totalCostEuro: number;
    averageCostEuro: number;
    totalIncidents: number;
    incidentRatePercentage: number;
}

export interface ReturnAnalyticsReport {
    totalReturns: number;
    totalEstimatedValueEuro: number;
    averageValueEuro: number;
    requiresHumanReviewCount: number;
}

export interface CustomerExperienceReport {
    totalTickets: number;
    resolvedTickets: number;
    resolutionRatePercentage: number;
    sentimentDistribution: {
        Positive: number;
        Neutral: number;
        Negative: number;
    };
}

/**
 * 1. Agregación para Operaciones de Almacén (Ana Whitfield)
 * Consolida el estado global del inventario entre ambos almacenes.
 */
export const generateWarehouseStockReport = (inventory: SKUInventory[]): WarehouseStockReport => {
    if (!inventory || inventory.length === 0) {
        return { totalSKUs: 0, totalStockLA: 0, totalStockZaragoza: 0, globalTotalStock: 0 };
    }

    return inventory.reduce((report, item) => {
        report.totalSKUs += 1;
        report.totalStockLA += item.stockLA;
        report.totalStockZaragoza += item.stockZaragoza;
        report.globalTotalStock += (item.stockLA + item.stockZaragoza);
        return report;
    }, { totalSKUs: 0, totalStockLA: 0, totalStockZaragoza: 0, globalTotalStock: 0 });
};

/**
 * 2. Agregación para Última Milla y Transportistas (Carlos Vega)
 * Analiza costes, volumen e incidencias para evaluar el rendimiento de la red de transporte.
 */
export const generateCarrierPerformanceReport = (shipments: CarrierShipment[]): CarrierPerformanceReport => {
    if (!shipments || shipments.length === 0) {
        return { totalShipments: 0, totalCostEuro: 0, averageCostEuro: 0, totalIncidents: 0, incidentRatePercentage: 0 };
    }

    const totals = shipments.reduce((report, shipment) => {
        report.totalShipments += 1;
        report.totalCostEuro += shipment.costEuro;
        if (shipment.hasIncident) {
            report.totalIncidents += 1;
        }
        return report;
    }, { totalShipments: 0, totalCostEuro: 0, totalIncidents: 0 });

    return {
        ...totals,
        averageCostEuro: totals.totalCostEuro / totals.totalShipments,
        incidentRatePercentage: (totals.totalIncidents / totals.totalShipments) * 100
    };
};

/**
 * 3. Agregación para Logística Inversa (Sofía Ramos)
 * Modela el impacto financiero de las devoluciones y la carga de revisión humana.
 */
export const generateReturnAnalyticsReport = (returns: OrderReturn[]): ReturnAnalyticsReport => {
    if (!returns || returns.length === 0) {
        return { totalReturns: 0, totalEstimatedValueEuro: 0, averageValueEuro: 0, requiresHumanReviewCount: 0 };
    }

    const totals = returns.reduce((report, item) => {
        report.totalReturns += 1;
        report.totalEstimatedValueEuro += item.estimatedValueEuro;
        if (item.requiresHumanReview) {
            report.requiresHumanReviewCount += 1;
        }
        return report;
    }, { totalReturns: 0, totalEstimatedValueEuro: 0, requiresHumanReviewCount: 0 });

    return {
        ...totals,
        averageValueEuro: totals.totalEstimatedValueEuro / totals.totalReturns
    };
};

/**
 * 4. Agregación para Experiencia del Cliente (Valentina Cruz)
 * Procesa el volumen de tickets, tasas de resolución y distribución de análisis de sentimiento.
 */
export const generateCustomerExperienceReport = (tickets: CustomerTicket[]): CustomerExperienceReport => {
    const defaultReport: CustomerExperienceReport = {
        totalTickets: 0,
        resolvedTickets: 0,
        resolutionRatePercentage: 0,
        sentimentDistribution: { Positive: 0, Neutral: 0, Negative: 0 }
    };

    if (!tickets || tickets.length === 0) return defaultReport;

    const totals = tickets.reduce((report, ticket) => {
        report.totalTickets += 1;
        if (ticket.isResolved) {
            report.resolvedTickets += 1;
        }
        // Incrementa dinámicamente el contador según el tipo de sentimiento
        report.sentimentDistribution[ticket.sentiment] += 1;
        return report;
    }, {
        totalTickets: 0,
        resolvedTickets: 0,
        sentimentDistribution: { Positive: 0, Neutral: 0, Negative: 0 }
    });

    return {
        ...totals,
        resolutionRatePercentage: (totals.resolvedTickets / totals.totalTickets) * 100
    };
};