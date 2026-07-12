import { SKUInventory, CarrierShipment, OrderReturn, BrandClient } from '../types/models';

/**
 * 1. Validaciones para Operaciones de Almacén (Ana Whitfield)
 * Verifica que los datos del SKU sean íntegros y determina si se debe disparar una alerta de stock bajo.
 */
export const isValidSKU = (sku: SKUInventory): boolean => {
    return (
        sku.sku.trim().length > 0 &&
        sku.productName.trim().length > 0 &&
        sku.clientBrand.trim().length > 0 &&
        sku.stockLA >= 0 &&
        sku.stockZaragoza >= 0 &&
        sku.minRequiredStock >= 0
    );
};

export const isStockLow = (sku: SKUInventory): boolean => {
    // TrackFlow necesita una visión unificada del inventario global
    const totalGlobalStock = sku.stockLA + sku.stockZaragoza;
    return totalGlobalStock < sku.minRequiredStock;
};

/**
 * 2. Validaciones para Última Milla (Carlos Vega)
 * Valida las restricciones físicas y logísticas básicas de un envío antes de asignarle un transportista.
 */
export const isValidShipment = (shipment: CarrierShipment): boolean => {
    return (
        shipment.id.trim().length > 0 &&
        shipment.trackingNumber.trim().length > 0 &&
        shipment.weightKg > 0 &&
        shipment.costEuro >= 0
    );
};

/**
 * 3. Validaciones para Logística Inversa (Sofía Ramos)
 * Aplica las reglas de negocio para determinar si una devolución requiere una costosa revisión humana
 * o si puede seguir un flujo automatizado.
 */
export const isValidReturn = (orderReturn: OrderReturn): boolean => {
    return (
        orderReturn.id.trim().length > 0 &&
        orderReturn.shipmentId.trim().length > 0 &&
        orderReturn.clientBrand.trim().length > 0 &&
        orderReturn.estimatedValueEuro >= 0
    );
};

export const evaluatesHumanReviewNecessity = (orderReturn: OrderReturn): boolean => {
    // Regla de negocio de TrackFlow: Si el producto está dañado/inservible tras la inspección de la IA,
    // o si el valor estimado supera los 150€, se fuerza la revisión humana para mitigar pérdidas.
    if (orderReturn.estimatedValueEuro > 150) {
        return true;
    }
    
    if (orderReturn.aiInspectionCondition === 'Damaged' || orderReturn.aiInspectionCondition === 'Unsalvageable') {
        return true;
    }

    return orderReturn.requiresHumanReview;
};

/**
 * 4. Validaciones para Comercial y Gestión de Clientes (Miguel Torres)
 * Analiza las fechas de vencimiento de contratos y los riesgos de fuga (churn) para alertar a los Account Managers.
 */
export const isValidClient = (client: BrandClient): boolean => {
    return (
        client.id.trim().length > 0 &&
        client.companyName.trim().length > 0 &&
        client.monthlyVolumeEuro >= 0 &&
        client.renewalRiskScore >= 0 &&
        client.renewalRiskScore <= 100
    );
};

export interface ContractAlerts {
    requires90DayAlert: boolean;
    requires30DayAlert: boolean;
    isHighRisk: boolean;
}

export const checkClientHealthAndDeadlines = (client: BrandClient): ContractAlerts => {
    const today = new Date(); // En entorno real, 2026-07-12
    const timeDiff = client.contractExpirationDate.getTime() - today.getTime();
    const daysToExpiration = Math.ceil(timeDiff / (1000 * 60 * 60 * 24));

    return {
        // Alertas solicitadas a los 90 y 30 días del vencimiento
        requires90DayAlert: daysToExpiration <= 90 && daysToExpiration > 30,
        requires30DayAlert: daysToExpiration <= 30 && daysToExpiration > 0,
        // TrackFlow considera riesgo crítico si la puntuación supera los 70 puntos
        isHighRisk: client.renewalRiskScore > 70
    };
};