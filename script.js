document.addEventListener('DOMContentLoaded', () => {

    const plateListContainer = document.getElementById('plate-list-container');
    const apiUrl = '1815.json';

    async function displayValidPlateNumbers() {
        plateListContainer.innerHTML = '<p>正在讀取車牌號碼...</p>';

        const response = await fetch(apiUrl);
        const allBusData = await response.json();
        const optionItemsHtml = allBusData
            .filter(bus => bus && typeof bus.PlateNumb !== 'undefined' && bus.PlateNumb !== "-1") 
            .map(bus => `<option value="${bus.PlateNumb}">${bus.PlateNumb}</option>`) 
            .join(''); 

        plateListContainer.innerHTML = optionItemsHtml
            ? `<select id="plate-select">${optionItemsHtml}</select>` 
            : '<p>沒有符合條件的車牌可顯示。</p>'; 
    }
    displayValidPlateNumbers();
});