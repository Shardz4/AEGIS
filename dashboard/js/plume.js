/**
 * Handles drawing and animating the Gaussian Plume consequence boundary
 */

export class PlumeDrawer {
    constructor() {
        this.currentRadius = 0.0; // In meters
        this.targetRadius = 0.0;
        this.pulsePhase = 0.0;
    }

    setTargetRadius(radiusMeters) {
        this.targetRadius = radiusMeters || 0.0;
    }

    update(dt) {
        // Interpolate current radius towards target radius for smooth sizing transitions
        const lerpSpeed = 1.5; // Meters per second or speed factor
        const diff = this.targetRadius - this.currentRadius;
        
        if (Math.abs(diff) < 0.1) {
            this.currentRadius = this.targetRadius;
        } else {
            this.currentRadius += diff * Math.min(1.0, lerpSpeed * dt);
        }

        // Advance pulse phase for the flashing perimeter rings
        this.pulsePhase += dt * 3.0; // speed of pulsing
    }

    draw(ctx, originX, originY, scalePixelsPerMeter) {
        if (this.currentRadius <= 0.0) return;

        const radiusPx = this.currentRadius * scalePixelsPerMeter;
        
        // Save state
        ctx.save();

        // 1. Draw radial gradient fill
        const gradient = ctx.createRadialGradient(
            originX, originY, 0, 
            originX, originY, radiusPx
        );
        
        // Transparent red gradient: opaque at center, fading out to edges
        gradient.addColorStop(0, 'rgba(255, 58, 58, 0.45)');
        gradient.addColorStop(0.5, 'rgba(255, 58, 58, 0.25)');
        gradient.addColorStop(1, 'rgba(255, 58, 58, 0.0)');
        
        ctx.beginPath();
        ctx.arc(originX, originY, radiusPx, 0, Math.PI * 2);
        ctx.fillStyle = gradient;
        ctx.fill();

        // 2. Draw animated outer safety boundary rings (representing 25% and 50% threshold bands)
        // Pulsing scale factor
        const pulseOffset = Math.sin(this.pulsePhase) * 2.0; // +- 2px
        
        // Outer boundary line
        ctx.beginPath();
        ctx.arc(originX, originY, Math.max(1, radiusPx + pulseOffset), 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(255, 58, 58, 0.6)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]); // Dashed line
        ctx.stroke();

        // Inner concentration rings
        ctx.beginPath();
        ctx.arc(originX, originY, radiusPx * 0.5, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(255, 58, 58, 0.3)';
        ctx.lineWidth = 1.0;
        ctx.setLineDash([4, 4]);
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(originX, originY, radiusPx * 0.25, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(255, 58, 58, 0.2)';
        ctx.lineWidth = 1.0;
        ctx.setLineDash([2, 4]);
        ctx.stroke();

        // Restore state
        ctx.restore();
    }
}
