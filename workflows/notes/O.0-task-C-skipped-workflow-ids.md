# O.0 Task C — Remove-from-Marketing Workflow IDs (follow-up tracking)

Each of the 3 marketing-removal stubs was implemented as 5 chained httpRequest DELETE calls
(the FIRST 5 of each GHL workflow_id array). The remaining IDs below are NOT yet implemented
and require a follow-up pass before go-live (otherwise contacts are only partially removed
from marketing sequences).

## unsuffixed stub -> Remove from Marketing WF [16] 1-5/5
Total: 43 | Implemented first 5: ['85f4600a-a55d-4fb5-bd62-d2886dc3d461', '74c90736-6550-4504-881d-2849231aa63c', '2d404941-fc8b-46c7-a310-2acd176eb2f9', 'd526e09e-4922-42d5-9634-5e2fcc3e5222', '0c7b2137-76fd-46d9-9f9b-75d095d3d769']
REMAINING (38):
  - e3ad4b2f-8ef8-4978-aeec-9732a8db9fc1
  - 92c5d673-dede-4b4a-9629-3a4a7f9bd1e9
  - 5dc8f50f-91da-4132-bfc5-b9473391b36e
  - da06ee55-2ab0-450d-981a-0e50703f4b4d
  - ea3c3aed-77a4-470d-bc3c-1b1765bfff3b
  - 750f1b7f-e688-47fa-ba52-d0ca6d7032ab
  - 2094441c-1366-40a3-b7a6-acfa1385fe88
  - 411b0101-d689-4456-86dc-3ab3bbe2c396
  - 18cebbaf-1acb-4978-b417-bcb333325560
  - 69fdc012-cefc-4917-b156-d6dbc8d13b7c
  - cdef8971-ff1a-47fc-8137-29fffad0c1af
  - 673b0fa7-7206-4c75-8eba-47d00f228143
  - d693f40a-9dd6-4d54-ab07-da76669cdc39
  - e88365f4-3ea2-4979-a793-9062142c1a7a
  - d46ac4d2-2cb1-4ddd-a44c-3d3744848d9d
  - a923858e-9f87-41a2-aa38-a8c4dacf97bd
  - dc355550-8dfc-42bc-a4de-923233a96727
  - 27eb4d09-7e3d-41de-a64e-8101cd270dca
  - 40d77229-555d-49da-9987-9c57db191c0c
  - 613dbbbd-b7af-4be0-81fa-371f3e1d7b14
  - faf891b0-d2cb-457a-b525-dec9ad57c7a0
  - 15f47572-9ffc-453d-995d-a1890441f290
  - 272e7b9d-5b9b-475d-8df7-8c5aa29a232c
  - dc850226-d693-4911-b255-ade8280a0815
  - ea7067d5-accf-48e5-97c3-09e1a06dec3f
  - bf894396-1cd9-4095-8789-7ce12a4e412a
  - 7853c4e2-5fdd-4ffd-98ae-07daedb00098
  - 56728a05-09cf-40ae-8b52-02d9849f4a95
  - 4737e00d-052e-44fd-a7e8-d238fb7196b5
  - c3bb12bb-b641-4de1-bd88-7fe244c4745b
  - 142611f6-52e2-4081-ac5a-2a3269b8807b
  - 0aef24f5-0234-4cb5-a127-f67b3b4b7747
  - fc8a2dd2-caa7-432a-9aae-2a64dd19fa80
  - f99fba97-6d2f-4fd6-966c-b5e5e36f8938
  - a708de2e-3ff4-440f-8d2b-39b3c49d7f06
  - 0a6a1349-0b44-429b-91e1-4c5be264cd9f
  - 2010003b-768f-4cba-a945-ea7fd0d25738
  - 58cc5caf-46de-416e-bd67-78398d7ff55d

## #2 -> Remove from Marketing WF [581] 1-5/5
Total: 43 | Implemented first 5: ['85f4600a-a55d-4fb5-bd62-d2886dc3d461', '74c90736-6550-4504-881d-2849231aa63c', '58cc5caf-46de-416e-bd67-78398d7ff55d', '2d404941-fc8b-46c7-a310-2acd176eb2f9', 'd526e09e-4922-42d5-9634-5e2fcc3e5222']
REMAINING (38):
  - 0c7b2137-76fd-46d9-9f9b-75d095d3d769
  - e3ad4b2f-8ef8-4978-aeec-9732a8db9fc1
  - 92c5d673-dede-4b4a-9629-3a4a7f9bd1e9
  - 2094441c-1366-40a3-b7a6-acfa1385fe88
  - dc850226-d693-4911-b255-ade8280a0815
  - ea7067d5-accf-48e5-97c3-09e1a06dec3f
  - bf894396-1cd9-4095-8789-7ce12a4e412a
  - 4737e00d-052e-44fd-a7e8-d238fb7196b5
  - c3bb12bb-b641-4de1-bd88-7fe244c4745b
  - 5dc8f50f-91da-4132-bfc5-b9473391b36e
  - da06ee55-2ab0-450d-981a-0e50703f4b4d
  - 7853c4e2-5fdd-4ffd-98ae-07daedb00098
  - 56728a05-09cf-40ae-8b52-02d9849f4a95
  - ea3c3aed-77a4-470d-bc3c-1b1765bfff3b
  - e88365f4-3ea2-4979-a793-9062142c1a7a
  - 411b0101-d689-4456-86dc-3ab3bbe2c396
  - 69fdc012-cefc-4917-b156-d6dbc8d13b7c
  - cdef8971-ff1a-47fc-8137-29fffad0c1af
  - 673b0fa7-7206-4c75-8eba-47d00f228143
  - 142611f6-52e2-4081-ac5a-2a3269b8807b
  - d46ac4d2-2cb1-4ddd-a44c-3d3744848d9d
  - 0aef24f5-0234-4cb5-a127-f67b3b4b7747
  - a923858e-9f87-41a2-aa38-a8c4dacf97bd
  - dc355550-8dfc-42bc-a4de-923233a96727
  - 27eb4d09-7e3d-41de-a64e-8101cd270dca
  - 40d77229-555d-49da-9987-9c57db191c0c
  - f99fba97-6d2f-4fd6-966c-b5e5e36f8938
  - a708de2e-3ff4-440f-8d2b-39b3c49d7f06
  - 0a6a1349-0b44-429b-91e1-4c5be264cd9f
  - 613dbbbd-b7af-4be0-81fa-371f3e1d7b14
  - faf891b0-d2cb-457a-b525-dec9ad57c7a0
  - fc8a2dd2-caa7-432a-9aae-2a64dd19fa80
  - a2c046bd-ecc7-4003-ab54-72304b3ee22a
  - 15f47572-9ffc-453d-995d-a1890441f290
  - fdf4ad82-33ab-4e73-b581-18d21d51ac42
  - 2010003b-768f-4cba-a945-ea7fd0d25738
  - 750f1b7f-e688-47fa-ba52-d0ca6d7032ab
  - fd3d777a-25e0-4b49-8de8-971e22f64aea

## #3 -> Remove from Marketing WF [587] 1-5/5
Total: 44 | Implemented first 5: ['85f4600a-a55d-4fb5-bd62-d2886dc3d461', '74c90736-6550-4504-881d-2849231aa63c', '2d404941-fc8b-46c7-a310-2acd176eb2f9', 'd526e09e-4922-42d5-9634-5e2fcc3e5222', '0c7b2137-76fd-46d9-9f9b-75d095d3d769']
REMAINING (39):
  - e3ad4b2f-8ef8-4978-aeec-9732a8db9fc1
  - 92c5d673-dede-4b4a-9629-3a4a7f9bd1e9
  - 5dc8f50f-91da-4132-bfc5-b9473391b36e
  - da06ee55-2ab0-450d-981a-0e50703f4b4d
  - ea3c3aed-77a4-470d-bc3c-1b1765bfff3b
  - 750f1b7f-e688-47fa-ba52-d0ca6d7032ab
  - 2094441c-1366-40a3-b7a6-acfa1385fe88
  - 411b0101-d689-4456-86dc-3ab3bbe2c396
  - 18cebbaf-1acb-4978-b417-bcb333325560
  - 69fdc012-cefc-4917-b156-d6dbc8d13b7c
  - cdef8971-ff1a-47fc-8137-29fffad0c1af
  - 673b0fa7-7206-4c75-8eba-47d00f228143
  - d693f40a-9dd6-4d54-ab07-da76669cdc39
  - e88365f4-3ea2-4979-a793-9062142c1a7a
  - d46ac4d2-2cb1-4ddd-a44c-3d3744848d9d
  - a923858e-9f87-41a2-aa38-a8c4dacf97bd
  - dc355550-8dfc-42bc-a4de-923233a96727
  - 27eb4d09-7e3d-41de-a64e-8101cd270dca
  - 40d77229-555d-49da-9987-9c57db191c0c
  - 613dbbbd-b7af-4be0-81fa-371f3e1d7b14
  - faf891b0-d2cb-457a-b525-dec9ad57c7a0
  - fdf4ad82-33ab-4e73-b581-18d21d51ac42
  - 15f47572-9ffc-453d-995d-a1890441f290
  - 272e7b9d-5b9b-475d-8df7-8c5aa29a232c
  - dc850226-d693-4911-b255-ade8280a0815
  - ea7067d5-accf-48e5-97c3-09e1a06dec3f
  - bf894396-1cd9-4095-8789-7ce12a4e412a
  - 7853c4e2-5fdd-4ffd-98ae-07daedb00098
  - 56728a05-09cf-40ae-8b52-02d9849f4a95
  - 4737e00d-052e-44fd-a7e8-d238fb7196b5
  - c3bb12bb-b641-4de1-bd88-7fe244c4745b
  - 142611f6-52e2-4081-ac5a-2a3269b8807b
  - 0aef24f5-0234-4cb5-a127-f67b3b4b7747
  - fc8a2dd2-caa7-432a-9aae-2a64dd19fa80
  - f99fba97-6d2f-4fd6-966c-b5e5e36f8938
  - a708de2e-3ff4-440f-8d2b-39b3c49d7f06
  - 0a6a1349-0b44-429b-91e1-4c5be264cd9f
  - 2010003b-768f-4cba-a945-ea7fd0d25738
  - 58cc5caf-46de-416e-bd67-78398d7ff55d
