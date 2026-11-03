// GBMS Main Application JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Auto-hide alerts after 5 seconds
    setTimeout(function() {
        document.querySelectorAll('.alert').forEach(function(alert) {
            alert.style.transition = 'opacity 0.5s';
            alert.style.opacity = '0';
            setTimeout(function() {
                alert.remove();
            }, 500);
        });
    }, 5000);

    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Stock validation for delivery form
    const deliveryForm = document.getElementById('delivery-form');
    if (deliveryForm) {
        deliveryForm.addEventListener('submit', async function(e) {
            const productSelect = document.getElementById('id_product');
            const quantityInput = document.getElementById('id_quantity');
            
            if (productSelect && quantityInput) {
                const productId = productSelect.value;
                const quantity = parseInt(quantityInput.value);
                
                if (productId && quantity > 0) {
                    try {
                        const response = await fetch(`/products/${productId}/stock/`);
                        const data = await response.json();
                        
                        if (quantity > data.stock_quantity) {
                            e.preventDefault();
                            alert(`⚠️ Insufficient Stock!\nAvailable: ${data.stock_quantity} units.\nRequested: ${quantity} units.`);
                            return false;
                        }
                    } catch (error) {
                        console.error('Stock validation error:', error);
                    }
                }
            }
        });
    }
});

