<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	const i18n = getContext('i18n');

	import {
		getConnectionStatus,
		initiateAttioConnection,
		checkAttioConnection,
		getAttioSyncStatus,
		triggerAttioSync,
		initiateNotionConnection,
		checkNotionConnection,
		getNotionSyncStatus,
		triggerNotionSync,
		initiateGDocsConnection,
		checkGDocsConnection,
		getGDocsSyncStatus,
		triggerGDocsSync,
		type ConnectionStatusResponse
	} from '$lib/apis/connections';
	import { user } from '$lib/stores';

	import Modal from '$lib/components/common/Modal.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	export let show = false;

	// Connection states
	let connectionStatuses: ConnectionStatusResponse | null = null;
	let loading = false;
	let connecting: { [key: string]: boolean } = {
		attio: false,
		notion: false,
		gdocs: false
	};

	// Sync status states
	let syncStatuses: {
		[key: string]: {
			status: string | null;
			last_sync: string | null;
			notes_count?: number;
			pages_count?: number;
			docs_count?: number;
		};
	} = {};
	let syncStatusPolling: ReturnType<typeof setInterval> | null = null;

	// Polling state
	let pollingInterval: ReturnType<typeof setInterval> | null = null;
	let pollingTimeout: ReturnType<typeof setTimeout> | null = null;
	let popupWindow: Window | null = null;

	// Available connections list
	const connections = [
		{
			id: 'notion',
			name: 'Notion',
			description: 'Import pages and databases from Notion',
			icon: 'notion'
		},
		{
			id: 'gdocs',
			name: 'Google Docs',
			description: 'Import documents from Google Drive',
			icon: 'gdocs'
		}
	];

	// Load connection status when modal opens
	$: if (show) {
		loadConnectionStatus();
	} else {
		stopSyncPolling();
	}

	const loadConnectionStatus = async () => {
		loading = true;
		try {
			const status = await getConnectionStatus($user.token);
			connectionStatuses = status;
			// Loop through connected services and fetch their sync status immediately
			pollSyncStatus();
		} catch (error) {
			console.error('Error loading connection status:', error);
			toast.error($i18n.t('Failed to load connection status'));
		} finally {
			loading = false;
		}
	};

	const handleConnect = async (connectionId: string) => {
		if (connectionId === 'attio') {
			await connectAttio();
		} else if (connectionId === 'notion') {
			await connectNotion();
		} else if (connectionId === 'gdocs') {
			await connectGDocs();
		}
	};

	const connectAttio = async () => {
		connecting.attio = true;

		try {
			// Initiate connection
			const response = await initiateAttioConnection($user.token);

			if (response.status === 'already_connected') {
				toast.success($i18n.t('Attio is already connected'));
				await loadConnectionStatus();
				connecting.attio = false;
				return;
			}

			// Open popup window
			const width = 600;
			const height = 700;
			const left = window.innerWidth / 2 - width / 2;
			const top = window.innerHeight / 2 - height / 2;

			popupWindow = window.open(
				response.redirect_url,
				'Attio OAuth',
				`width=${width},height=${height},left=${left},top=${top}`
			);

			if (!popupWindow) {
				toast.error($i18n.t('Please allow popups for this site'));
				connecting.attio = false;
				return;
			}

			// Start polling
			startPolling();
		} catch (error) {
			console.error('Error initiating Attio connection:', error);
			toast.error($i18n.t('Failed to initiate Attio connection'));
			connecting.attio = false;
		}
	};

	const startPolling = () => {
		let pollCount = 0;
		const maxPolls = 30; // 30 polls * 2 seconds = 60 seconds timeout

		// Poll every 2 seconds
		pollingInterval = setInterval(async () => {
			pollCount++;

			// Check if popup is closed
			if (popupWindow && popupWindow.closed) {
				stopPolling();
				toast.info($i18n.t('Authentication window closed'));
				connecting.attio = false;
				return;
			}

			// Check connection status
			try {
				const status = await checkAttioConnection($user.token);

				if (status.connected) {
					// Connection successful!
					stopPolling();
					toast.success($i18n.t('Attio connected successfully!'));
					connecting.attio = false;

					// Close popup if still open
					if (popupWindow && !popupWindow.closed) {
						popupWindow.close();
					}

					// Reload connection status
					await loadConnectionStatus();

					// Trigger sync after small delay to ensure permissions are fully granted
					setTimeout(async () => {
						try {
							await triggerAttioSync($user.token);
							console.log('Attio sync triggered successfully');
							// Start polling sync status
							pollSyncStatus();
						} catch (error) {
							console.error('Error triggering Attio sync:', error);
						}
					}, 3000); // 3 second delay
				} else if (pollCount >= maxPolls) {
					// Timeout
					stopPolling();
					toast.error($i18n.t('Connection timed out. Please try again.'));
					connecting.attio = false;

					// Close popup if still open
					if (popupWindow && !popupWindow.closed) {
						popupWindow.close();
					}
				}
			} catch (error) {
				console.error('Error checking connection:', error);
			}
		}, 2000);
	};

	const stopPolling = () => {
		if (pollingInterval) {
			clearInterval(pollingInterval);
			pollingInterval = null;
		}
		if (pollingTimeout) {
			clearTimeout(pollingTimeout);
			pollingTimeout = null;
		}
		popupWindow = null;
	};

	// Cleanup on component destroy
	$: if (!show) {
		stopPolling();
	}

	const connectNotion = async () => {
		connecting.notion = true;

		try {
			// Initiate connection
			const response = await initiateNotionConnection($user.token);

			if (response.status === 'already_connected') {
				toast.success($i18n.t('Notion is already connected'));
				await loadConnectionStatus();
				connecting.notion = false;
				return;
			}

			// Open popup window
			const width = 600;
			const height = 700;
			const left = window.innerWidth / 2 - width / 2;
			const top = window.innerHeight / 2 - height / 2;

			popupWindow = window.open(
				response.redirect_url,
				'Notion OAuth',
				`width=${width},height=${height},left=${left},top=${top}`
			);

			if (!popupWindow) {
				toast.error($i18n.t('Please allow popups for this site'));
				connecting.notion = false;
				return;
			}

			// Start polling
			startNotionPolling();
		} catch (error) {
			console.error('Error initiating Notion connection:', error);
			toast.error($i18n.t('Failed to initiate Notion connection'));
			connecting.notion = false;
		}
	};

	const startNotionPolling = () => {
		let pollCount = 0;
		const maxPolls = 30; // 30 polls * 2 seconds = 60 seconds timeout

		// Poll every 2 seconds
		pollingInterval = setInterval(async () => {
			pollCount++;

			// Check if popup is closed
			if (popupWindow && popupWindow.closed) {
				stopPolling();
				toast.info($i18n.t('Authentication window closed'));
				connecting.notion = false;
				return;
			}

			// Check connection status
			try {
				const status = await checkNotionConnection($user.token);

				if (status.connected) {
					// Connection successful!
					stopPolling();
					toast.success($i18n.t('Notion connected successfully!'));
					connecting.notion = false;

					// Close popup if still open
					if (popupWindow && !popupWindow.closed) {
						popupWindow.close();
					}

					// Reload connection status
					await loadConnectionStatus();

					// Trigger sync after small delay to ensure permissions are fully granted
					setTimeout(async () => {
						try {
							await triggerNotionSync($user.token);
							console.log('Notion sync triggered successfully');
							// Start polling sync status
							pollSyncStatus();
						} catch (error) {
							console.error('Error triggering Notion sync:', error);
						}
					}, 3000); // 3 second delay
				} else if (pollCount >= maxPolls) {
					// Timeout
					stopPolling();
					toast.error($i18n.t('Connection timed out. Please try again.'));
					connecting.notion = false;

					// Close popup if still open
					if (popupWindow && !popupWindow.closed) {
						popupWindow.close();
					}
				}
			} catch (error) {
				console.error('Error checking connection:', error);
			}
		}, 2000);
	};

	const connectGDocs = async () => {
		connecting.gdocs = true;

		try {
			const response = await initiateGDocsConnection($user.token);

			if (response.status === 'already_connected') {
				toast.success($i18n.t('Google Docs is already connected'));
				await loadConnectionStatus();
				connecting.gdocs = false;
				return;
			}

			const width = 600;
			const height = 700;
			const left = window.innerWidth / 2 - width / 2;
			const top = window.innerHeight / 2 - height / 2;

			popupWindow = window.open(
				response.redirect_url,
				'Google Docs OAuth',
				`width=${width},height=${height},left=${left},top=${top}`
			);

			if (!popupWindow) {
				toast.error($i18n.t('Please allow popups for this site'));
				connecting.gdocs = false;
				return;
			}

			startGDocsPolling();
		} catch (error) {
			console.error('Error initiating Google Docs connection:', error);
			toast.error($i18n.t('Failed to initiate Google Docs connection'));
			connecting.gdocs = false;
		}
	};

	const startGDocsPolling = () => {
		let pollCount = 0;
		const maxPolls = 30;

		pollingInterval = setInterval(async () => {
			pollCount++;

			if (popupWindow && popupWindow.closed) {
				stopPolling();
				toast.info($i18n.t('Authentication window closed'));
				connecting.gdocs = false;
				return;
			}

			try {
				const status = await checkGDocsConnection($user.token);

				if (status.connected) {
					stopPolling();
					toast.success($i18n.t('Google Docs connected successfully!'));
					connecting.gdocs = false;

					if (popupWindow && !popupWindow.closed) {
						popupWindow.close();
					}

					await loadConnectionStatus();

					setTimeout(async () => {
						try {
							await triggerGDocsSync($user.token);
							console.log('Google Docs sync triggered successfully');
							pollSyncStatus();
						} catch (error) {
							console.error('Error triggering Google Docs sync:', error);
						}
					}, 3000);
				} else if (pollCount >= maxPolls) {
					stopPolling();
					toast.error($i18n.t('Connection timed out. Please try again.'));
					connecting.gdocs = false;

					if (popupWindow && !popupWindow.closed) {
						popupWindow.close();
					}
				}
			} catch (error) {
				console.error('Error checking connection:', error);
			}
		}, 2000);
	};

	const pollSyncStatus = async () => {
		// Poll sync status every 5 seconds for connected connections
		if (connectionStatuses?.attio?.connected) {
			try {
				const status = await getAttioSyncStatus($user.token);
				syncStatuses['attio'] = status;

				// Continue polling if in progress
				if (status.status === 'in_progress') {
					if (!syncStatusPolling) {
						syncStatusPolling = setInterval(async () => {
							try {
								const updatedStatus = await getAttioSyncStatus($user.token);
								syncStatuses['attio'] = updatedStatus;

								if (updatedStatus.status !== 'in_progress') {
									stopSyncPolling();
								}
							} catch (error) {
								console.error('Error polling sync status:', error);
							}
						}, 5000);
					}
				}
			} catch (error) {
				console.error('Error loading sync status:', error);
			}
		}

		// Notion
		if (connectionStatuses?.notion?.connected) {
			try {
				const status = await getNotionSyncStatus($user.token);
				syncStatuses['notion'] = status;

				// Continue polling if in progress
				if (status.status === 'in_progress') {
					if (!syncStatusPolling) {
						syncStatusPolling = setInterval(async () => {
							try {
								const updatedStatus = await getNotionSyncStatus($user.token);
								syncStatuses['notion'] = updatedStatus;

								if (updatedStatus.status !== 'in_progress') {
									stopSyncPolling();
								}
							} catch (error) {
								console.error('Error polling Notion sync status:', error);
							}
						}, 5000);
					}
				}
			} catch (error) {
				console.error('Error loading Notion sync status:', error);
			}
		}

		// Google Docs
		if (connectionStatuses?.gdocs?.connected) {
			try {
				const status = await getGDocsSyncStatus($user.token);
				syncStatuses['gdocs'] = status;

				if (status.status === 'in_progress') {
					if (!syncStatusPolling) {
						syncStatusPolling = setInterval(async () => {
							try {
								const updatedStatus = await getGDocsSyncStatus($user.token);
								syncStatuses['gdocs'] = updatedStatus;

								if (updatedStatus.status !== 'in_progress') {
									stopSyncPolling();
								}
							} catch (error) {
								console.error('Error polling Google Docs sync status:', error);
							}
						}, 5000);
					}
				}
			} catch (error) {
				console.error('Error loading Google Docs sync status:', error);
			}
		}
	};

	const stopSyncPolling = () => {
		if (syncStatusPolling) {
			clearInterval(syncStatusPolling);
			syncStatusPolling = null;
		}
	};

	const formatDate = (isoDate: string | null) => {
		if (!isoDate) return 'Never';
		try {
			const date = new Date(isoDate);
			const now = new Date();
			const diffMs = now.getTime() - date.getTime();
			const diffMins = Math.floor(diffMs / 60000);

			if (diffMins < 1) return 'Just now';
			if (diffMins < 60) return `${diffMins}m ago`;
			if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
			return `${Math.floor(diffMins / 1440)}d ago`;
		} catch {
			return isoDate;
		}
	};
</script>

<Modal size="md" bind:show>
	<div class="relative">
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class=" text-lg font-medium self-center">
				{$i18n.t('Connections')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-5'} />
			</button>
		</div>

		<div class="flex flex-col w-full px-5 pb-4 md:space-y-4 dark:text-gray-200">
			<p class="text-sm text-gray-600 dark:text-gray-400 pt-2">
				{$i18n.t('Connect external services to import context into your knowledge base')}
			</p>

			<!-- Connections List -->
			<div class="flex flex-col space-y-2 mt-4">
				{#if loading}
					<div class="flex justify-center items-center py-8">
						<Spinner className="size-6" />
					</div>
				{:else}
					<div class="max-h-96 overflow-y-auto space-y-2">
						{#each connections as connection (connection.id)}
							{@const isConnected = connectionStatuses?.[connection.id]?.connected ?? false}
							{@const isConnecting = connecting[connection.id]}

							<div
								class="group flex items-center justify-between p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 /50 transition"
							>
								<div class="flex items-center gap-3 flex-1 min-w-0">
									<!-- Icon placeholder -->
									<div
										class="flex-shrink-0 size-10 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center"
									>
										{#if connection.icon === 'attio'}
											<!-- Attio icon -->
											<svg
												class="size-6 text-purple-600 dark:text-purple-400"
												viewBox="0 0 24 24"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<path
													d="M12 4L4 8L12 12L20 8L12 4Z"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M4 12L12 16L20 12"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M4 16L12 20L20 16"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
											</svg>
										{:else if connection.icon === 'notion'}
											<!-- Notion icon -->
											<svg
												class="size-6 text-black dark:text-white"
												viewBox="0 0 24 24"
												fill="currentColor"
												xmlns="http://www.w3.org/2000/svg"
											>
												<path
													d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.933zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.139c-.093-.514.28-.887.747-.933z"
												/>
											</svg>
										{:else if connection.icon === 'gdocs'}
											<!-- Google Docs icon -->
											<svg
												class="size-6"
												viewBox="0 0 24 24"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<path
													d="M14 2H6C5.46957 2 4.96086 2.21071 4.58579 2.58579C4.21071 2.96086 4 3.46957 4 4V20C4 20.5304 4.21071 21.0391 4.58579 21.4142C4.96086 21.7893 5.46957 22 6 22H18C18.5304 22 19.0391 21.7893 19.4142 21.4142C19.7893 21.0391 20 20.5304 20 20V8L14 2Z"
													fill="#4285F4"
													stroke="#4285F4"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M14 2V8H20"
													fill="white"
													stroke="white"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
												<path
													d="M16 13H8M16 17H8M10 9H8"
													stroke="white"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												/>
											</svg>
										{/if}
									</div>

									<!-- Connection info -->
									<div class="flex-1 min-w-0">
										<p class="font-medium text-sm">
											{connection.name}
										</p>
										<p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
											{connection.description}
										</p>

										<!-- Sync status footer -->
										{#if isConnected && syncStatuses[connection.id]}
											<p class="text-xs mt-1.5">
												{#if syncStatuses[connection.id].status === 'in_progress'}
													<span class="text-blue-600 dark:text-blue-400">
														⟳ Syncing context...
													</span>
												{:else if syncStatuses[connection.id].status === 'success'}
													<span class="text-green-600 dark:text-green-400">
														✓
														{#if connection.id === 'attio'}
															{syncStatuses[connection.id].notes_count || 0} notes synced
														{:else if connection.id === 'notion'}
															{syncStatuses[connection.id].pages_count || 0} pages synced
														{:else if connection.id === 'gdocs'}
															{syncStatuses[connection.id].docs_count || 0} docs synced
														{/if}
														· Last: {formatDate(syncStatuses[connection.id].last_sync)}
													</span>
												{:else if syncStatuses[connection.id].status === 'failed'}
													<span class="text-red-600 dark:text-red-400">
														✗ Sync failed · Try reconnecting
													</span>
												{/if}
											</p>
										{/if}
									</div>
								</div>

								<!-- Connect/Connected button -->
								{#if isConnected}
									<div
										class="flex-shrink-0 px-4 py-2 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-lg font-medium text-sm flex items-center gap-2"
									>
										<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M5 13l4 4L19 7"
											/>
										</svg>
										{$i18n.t('Connected')}
									</div>
								{:else}
									<button
										class="flex-shrink-0 px-4 py-2 bg-gray-900 hover:bg-gray-800 dark:bg-gray-100 dark:hover:bg-gray-200 text-white dark:text-gray-900 rounded-lg font-medium text-sm transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
										on:click={() => handleConnect(connection.id)}
										disabled={isConnecting}
									>
										{#if isConnecting}
											<Spinner className="size-4" />
											{$i18n.t('Connecting...')}
										{:else}
											{$i18n.t('Connect')}
										{/if}
									</button>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>
