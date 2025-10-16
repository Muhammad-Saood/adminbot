// wallet.js - Wallet Connect Logic for TON

const tg = window.Telegram.WebApp;
tg.ready();
const userId = tg.initDataUnsafe.user.id;
document.getElementById('user-id').textContent = userId;

const MONETAG_ZONE = "{MONETAG_ZONE}";
const OWNER_WALLET = "{OWNER_WALLET}";
const USDT_CONTRACT = "{USDT_CONTRACT}";

let adStartTime = null;
let adCompleted = false;

const tonConnectUI = new TONConnectUI({
    manifestUrl: `${window.location.origin}/tonconnect-manifest.json`
});

tonConnectUI.onStatusChange(async (wallet) => {
    if (wallet) {
        const address = ton.Address.parseRaw(wallet.account.address).toString({ urlSafe: true, bounceable: true });
        await fetch(`/api/set_wallet/${userId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ wallet: address })
        });
        updateWalletUI();
    } else {
        await fetch(`/api/disconnect_wallet/${userId}`, { method: 'POST' });
        updateWalletUI();
    }
});

function getCachedUserData() {
    const cachedData = localStorage.getItem(`user_data_${userId}`);
    return cachedData ? JSON.parse(cachedData) : null;
}

function setCachedUserData(data) {
    localStorage.setItem(`user_data_${userId}`, JSON.stringify({
        points: data.points,
        total_daily_ads_watched: data.total_daily_ads_watched,
        daily_ads_watched: data.daily_ads_watched,
        invited_friends: data.invited_friends,
        connected_wallet: data.connected_wallet,
        plan_purchase_date: data.plan_purchase_date,
        plan_active: data.plan_active
    }));
}

async function loadData() {
    try {
        // Load cached data immediately
        const cachedData = getCachedUserData();
        if (cachedData) {
            document.getElementById('balance').textContent = cachedData.points.toFixed(2);
            document.getElementById('ad-limit').textContent = cachedData.total_daily_ads_watched + '/10';
            document.getElementById('invited-count').textContent = cachedData.invited_friends;
            document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;
        } else {
            // Show default state for first-time users
            document.getElementById('balance').textContent = '0.00';
            document.getElementById('ad-limit').textContent = '0/10';
            document.getElementById('invited-count').textContent = '0';
            document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;
            // Add loading indicators
            document.getElementById('balance').classList.add('loading');
            document.getElementById('ad-limit').classList.add('loading');
            document.getElementById('invited-count').classList.add('loading');
        }

        // Fetch fresh data from API
        const response = await fetch('/api/user/' + userId);
        const data = await response.json();
        // Update UI with fresh data
        document.getElementById('balance').textContent = data.points.toFixed(2);
        document.getElementById('balance').classList.remove('loading');
        document.getElementById('ad-limit').textContent = data.total_daily_ads_watched + '/10';
        document.getElementById('ad-limit').classList.remove('loading');
        document.getElementById('invited-count').textContent = data.invited_friends;
        document.getElementById('invited-count').classList.remove('loading');
        document.getElementById('invite-link').textContent = 'https://t.me/{BOT_USERNAME}?start=ref' + userId;

        // Cache the fresh data
        setCachedUserData(data);
        updateWalletUI();
    } catch (error) {
        // If API fails, keep cached data or show default
        if (!getCachedUserData()) {
            document.getElementById('balance').textContent = '0.00';
            document.getElementById('ad-limit').textContent = '0/10';
            document.getElementById('invited-count').textContent = '0';
            document.getElementById('balance').classList.remove('loading');
            document.getElementById('ad-limit').classList.remove('loading');
            document.getElementById('invited-count').classList.remove('loading');
        }
        tg.showAlert('Failed to load data');
    }
}

async function updateWalletUI() {
    const section = document.getElementById('wallet-connect-section');
    section.innerHTML = '';
    try {
        const response = await fetch('/api/user/' + userId);
        const data = await response.json();
        const connected = data.connected_wallet;
        const planActive = data.plan_active;
        const purchaseDate = data.plan_purchase_date;

        if (planActive) {
            const expiry = new Date(purchaseDate);
            expiry.setDate(expiry.getDate() + 7);
            section.innerHTML = `
                <div class="small-card">Plan Purchased, Valid until ${expiry.toDateString()}</div>
                <button disabled class="btn-primary">Purchased</button>
            `;
        } else {
            if (connected) {
                section.innerHTML = `
                    <div>Connected: <span>${connected.substring(0,6)}...${connected.substring(connected.length-6)}</span> <button id="disconnect">Disconnect</button></div>
                    <button id="purchase-plan" class="btn-primary">Purchase Plan (10 USDT)</button>
                `;
                document.getElementById('disconnect').addEventListener('click', () => tonConnectUI.disconnect());
                document.getElementById('purchase-plan').addEventListener('click', purchasePlan);
            } else {
                section.innerHTML = `
                    <button id="connect-wallet" class="btn-primary">Connect Wallet</button>
                `;
                document.getElementById('connect-wallet').addEventListener('click', () => tonConnectUI.connectWallet());
            }
        }
    } catch (error) {
        tg.showAlert('Failed to load wallet status');
    }
}

async function purchasePlan() {
    try {
        const { TonClient, Address, beginCell } = ton;
        const client = new TonClient({
            endpoint: 'https://toncenter.com/api/v2/jsonRPC',
        });

        const userAddress = tonConnectUI.wallet.account.address;
        const master = Address.parse(USDT_CONTRACT);
        const walletCell = beginCell().storeAddress(Address.parse(userAddress)).endCell();
        const response = await client.runMethod(master, 'get_wallet_address', [{ type: 'slice', cell: walletCell }]);
        const userJettonWallet = response.stack.readAddress();

        const payload = beginCell()
            .storeUint(0xf8a7ea5, 32)
            .storeUint(0, 64)
            .storeCoins(10000000)
            .storeAddress(Address.parse(OWNER_WALLET))
            .storeAddress(Address.parse(userAddress))
            .storeBit(0)
            .storeCoins(0)
            .storeBit(0)
            .endCell()
            .toB64();

        const tx = await tonConnectUI.sendTransaction({
            validUntil: Math.floor(Date.now() / 1000) + 360,
            messages: [{
                address: userJettonWallet.toString(),
                amount: '50000000',
                payload: payload
            }]
        });

        await fetch(`/api/purchase_plan/${userId}`, { method: 'POST' });
        tg.showAlert('Plan purchased successfully!');
        updateWalletUI();
        loadData();
    } catch (e) {
        tg.showAlert(`Transaction failed: ${e.message}`);
    }
}

async function watchAd() {
    const watchBtn = document.getElementById('ad-btn');
    watchBtn.disabled = true;
    watchBtn.textContent = 'Watching...';
    try {
        const userResponse = await fetch('/api/user/' + userId);
        const userData = await userResponse.json();

        if (!userData.plan_active) {
            tg.showAlert('Please purchase plan first!');
            watchBtn.disabled = false;
            watchBtn.textContent = 'Watch Ad';
            return;
        }

        if (userData.daily_ads_watched >= 10) {
            tg.showAlert('Daily ad limit reached!');
            await loadData();
            watchBtn.disabled = false;
            watchBtn.textContent = 'Watch Ad';
            return;
        }

        adStartTime = Date.now();
        adCompleted = false;

        // Start a timer to check ad completion
        setTimeout(() => {
            adCompleted = true;
        }, 17000); // 17 seconds

        await window[`show_${MONETAG_ZONE}`]();

        // Check if ad was watched for at least 17 seconds
        const response = await fetch('/api/watch_ad/' + userId, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ ad_completed: adCompleted })
        });
        const data = await response.json();
        if (data.success) {
            tg.showAlert('Ad watched! +0.1 USDT');
        } else if (data.limit_reached) {
            tg.showAlert('Daily ad limit reached!');
        } else if (data.message === 'Please purchase plan first') {
            tg.showAlert('Please purchase plan first!');
        } else if (data.message === 'Ad not completely watched or not opened ad website') {
            tg.showAlert('Ad not completely watched or not opened ad website');
        } else {
            tg.showAlert('Error watching ad');
        }
        await loadData();
    } catch (error) {
        tg.showAlert('Ad failed to load. Please turn off ad blocker or VPN');
    } finally {
        adStartTime = null;
        adCompleted = false;
        watchBtn.disabled = false;
        watchBtn.textContent = 'Watch Ad';
    }
}

async function copyLink() {
    try {
        const link = document.getElementById('invite-link').textContent;
        await navigator.clipboard.writeText(link);
        tg.showAlert('Link copied!');
    } catch (error) {
        tg.showAlert('Failed to copy link');
    }
}

async function withdraw() {
    const amount = parseFloat(document.getElementById('amount').value);
    const withdraw_wallet = document.getElementById('withdraw-wallet').value;
    if (amount < 1 || !withdraw_wallet) {
        tg.showAlert('Minimum 1 USDT and Wallet address required!');
        return;
    }
    const response = await fetch('/api/withdraw/' + userId, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({amount, withdraw_wallet})
    });
    const data = await response.json();
    if (data.success) {
        tg.showAlert('Withdraw successful! Credited within 24 hours.');
        document.getElementById('amount').value = '';
        document.getElementById('withdraw-wallet').value = '';
        await loadData();
    } else {
        tg.showAlert(data.message || 'Withdraw failed');
    }
}

function showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(page).classList.add('active');
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`.nav-btn[data-page="${page}"]`).classList.add('active');
    if (page === 'withdraw') {
        updateWalletUI();
    }

    // Check if ad was not watched for 17 seconds
    if (adStartTime && !adCompleted && page === 'tasks') {
        const timeElapsed = (Date.now() - adStartTime) / 1000;
        if (timeElapsed < 17) {
            adCompleted = false;
        }
    }
}

document.getElementById('ad-btn').addEventListener('click', watchAd);
document.getElementById('upgrade-plan').addEventListener('click', () => showPage('withdraw'));
loadData();
