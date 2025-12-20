<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	const i18n = getContext('i18n');

	import { uploadDocument, getDocuments, deleteDocumentById } from '$lib/apis/documents';
	import { user } from '$lib/stores';

	import Modal from '$lib/components/common/Modal.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	export let show = false;

	let documents = [];
	let loading = false;
	let uploading = false;
	let fileInputElement;
	let deletingDocumentId: string | null = null; // Track which document is being deleted

	// Format file size to human readable format
	const formatFileSize = (bytes: number): string => {
		if (bytes === 0) return '0 B';
		const k = 1024;
		const sizes = ['B', 'KB', 'MB', 'GB'];
		const i = Math.floor(Math.log(bytes) / Math.log(k));
		return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i];
	};

	// Format timestamp to human readable date
	const formatDate = (timestamp: number): string => {
		const date = new Date(timestamp * 1000);
		return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
	};

	// Load documents when modal opens
	$: if (show) {
		loadDocuments();
	}

	const loadDocuments = async () => {
		loading = true;
		try {
			const result = await getDocuments($user.token);
			if (result) {
				documents = result;
			}
		} catch (error) {
			console.error('Error loading documents:', error);
			toast.error($i18n.t('Failed to load documents'));
		} finally {
			loading = false;
		}
	};

	const handleFileSelect = async (event: Event) => {
		const target = event.target as HTMLInputElement;
		const files = target.files;

		if (!files || files.length === 0) return;

		uploading = true;

		// Upload each file
		for (const file of Array.from(files)) {
			try {
				await uploadDocument($user.token, file);
				toast.success($i18n.t(`Uploaded ${file.name} successfully`));
			} catch (error) {
				console.error('Error uploading file:', error);
				toast.error($i18n.t(`Failed to upload ${file.name}: ${error}`));
			}
		}

		uploading = false;

		// Reload documents list
		await loadDocuments();

		// Reset file input
		if (fileInputElement) {
			fileInputElement.value = '';
		}
	};

	const handleDelete = async (documentId: string, filename: string) => {
		// Prevent double-clicks
		if (deletingDocumentId) return;

		// Set deleting state
		deletingDocumentId = documentId;

		// Show loading toast
		const loadingToastId = toast.loading(
			$i18n.t(`Deleting ${filename}. Please do not go back or exit.`),
			{
				style: 'background-color: rgb(59 130 246); color: white;' // Blue background for dark theme
			}
		);

		try {
			await deleteDocumentById($user.token, documentId);

			// Dismiss loading toast
			toast.dismiss(loadingToastId);

			// Show success toast
			toast.success($i18n.t(`Deleted ${filename}`));

			// Remove from list
			documents = documents.filter((doc) => doc.id !== documentId);
		} catch (error) {
			console.error('Error deleting document:', error);

			// Dismiss loading toast
			toast.dismiss(loadingToastId);

			// Show error toast
			toast.error($i18n.t(`Failed to delete ${filename}`));
		} finally {
			// Reset deleting state
			deletingDocumentId = null;
		}
	};

	const openFilePicker = () => {
		fileInputElement?.click();
	};
</script>

<Modal size="md" bind:show>
	<div class="relative">
		<!-- Translucent loading overlay during deletion -->
		{#if deletingDocumentId}
			<div
				class="absolute inset-0 bg-black/50 dark:bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center rounded-xl"
			>
				<div class="text-center">
					<Spinner className="size-8 text-blue-500" />
					<p class="mt-3 text-white font-medium">{$i18n.t('Deleting document...')}</p>
				</div>
			</div>
		{/if}

		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-1">
			<div class=" text-lg font-medium self-center">
				{$i18n.t('Documents')}
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
			<!-- Add Files Button -->
			<div class="flex justify-between items-center pt-4">
				<button
					class="px-4 py-2 bg-gray-900 hover:bg-gray-800 dark:bg-gray-100 dark:hover:bg-gray-200 text-white dark:text-gray-900 rounded-lg font-medium transition flex items-center gap-2"
					on:click={openFilePicker}
					disabled={uploading}
				>
					{#if uploading}
						<Spinner className="size-4" />
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-5"
						>
							<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
						</svg>
					{/if}
					{uploading ? $i18n.t('Uploading...') : $i18n.t('Add Files')}
				</button>

				<input
					bind:this={fileInputElement}
					type="file"
					multiple
					accept=".doc,.docx,.pdf,.csv,.ppt,.pptx,.txt,.md,.xls,.xlsx"
					on:change={handleFileSelect}
					class="hidden"
				/>
			</div>

			<!-- Documents List -->
			<div class="flex flex-col space-y-2 mt-4">
				{#if loading}
					<div class="flex justify-center items-center py-8">
						<Spinner className="size-6" />
					</div>
				{:else if documents.length === 0}
					<div class="text-center py-8 text-gray-500">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-12 mx-auto mb-2 opacity-50"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
							/>
						</svg>
						<p>{$i18n.t('No documents uploaded yet')}</p>
						<p class="text-sm mt-1">{$i18n.t('Click "Add Files" to get started')}</p>
					</div>
				{:else}
					<div class="max-h-96 overflow-y-auto space-y-1">
						{#each documents as document (document.id)}
							<div
								class="group flex items-center justify-between p-3 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition"
							>
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="1.5"
											stroke="currentColor"
											class="size-5 flex-shrink-0 text-gray-600 dark:text-gray-400"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
											/>
										</svg>
										<div class="flex-1 min-w-0">
											<p class="font-medium text-sm truncate" title={document.filename}>
												{document.filename}
											</p>
											<p class="text-xs text-gray-500 dark:text-gray-400">
												{formatFileSize(document.size)} • {formatDate(document.created_at)}
											</p>
										</div>
									</div>
								</div>

								<button
									class="flex-shrink-0 p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition opacity-0 group-hover:opacity-100 disabled:opacity-50 disabled:cursor-not-allowed"
									on:click={() => handleDelete(document.id, document.filename)}
									disabled={deletingDocumentId === document.id}
									title={deletingDocumentId === document.id
										? $i18n.t('Deleting...')
										: $i18n.t('Delete')}
								>
									{#if deletingDocumentId === document.id}
										<!-- Loading spinner -->
										<svg
											class="animate-spin size-4"
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
										>
											<circle
												class="opacity-25"
												cx="12"
												cy="12"
												r="10"
												stroke="currentColor"
												stroke-width="4"
											></circle>
											<path
												class="opacity-75"
												fill="currentColor"
												d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
											></path>
										</svg>
									{:else}
										<!-- Delete icon -->
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="1.5"
											stroke="currentColor"
											class="size-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
											/>
										</svg>
									{/if}
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>
