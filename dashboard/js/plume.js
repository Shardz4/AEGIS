/**
 * Plume consequence boundary renderer — Monochrome
 * Uses only muted red for functional hazard indication.
 */
export class PlumeDrawer {
    constructor() {
        this.currentRadius = 0;
        this.targetRadius = 0;
        this.pulsePhase = 0;
    }

    setTargetRadius(r) {
        this.targetRadius = r || 0;
    }

    update(dt) {
        const diff = this.targetRadius - this.currentRadius;
        if (Math.abs(diff) < 0.1) {
            this.currentRadius = this.targetRadius;
        } else {
            this.currentRadius += diff * Math.min(1, 1.5 * dt);
        }
        this.pulsePhase += dt * 2.0;
    }

    draw(ctx, ox, oy, scale) {
        if (this.currentRadius <= 0) return;

        const r = this.currentRadius * scale;
        ctx.save();

        // Fill: very subtle radial gradient
        const grad = ctx.createRadialGradient(ox, oy, 0, ox, oy, r);
        grad.addColorStop(0, 'rgba(160, 50, 50, 0.18)');
        grad.addColorStop(0.6, 'rgba(160, 50, 50, 0.08)');
        grad.addColorStop(1, 'rgba(160, 50, 50, 0.0)');

        ctx.beginPath();
        ctx.arc(ox, oy, r, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();

        // Outer boundary — dashed, muted
        const pulseOff = Math.sin(this.pulsePhase) * 1.5;
        ctx.beginPath();
        ctx.arc(ox, oy, Math.max(1, r + pulseOff), 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(160, 50, 50, 0.4)';
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 4]);
        ctx.stroke();

        // 50% concentration ring
        ctx.beginPath();
        ctx.arc(ox, oy, r * 0.5, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(160, 50, 50, 0.2)';
        ctx.lineWidth = 0.5;
        ctx.setLineDash([3, 4]);
        ctx.stroke();

        ctx.restore();
    }
}
