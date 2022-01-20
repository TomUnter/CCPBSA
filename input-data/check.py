import pymol
pymol.finish_launching(['pymol', '-qc'])
cmd = pymol.cmd

cmd.load('1stn.pdb')
seq = cmd.get_fastastr('1stn')
print(seq)
seq = 'AAAAA' + "".join([i for i in seq.split('\n') if '>' not in i])
print(seq, len(seq))

aa1 = list("ACDEFGHIKLMNPQRSTVWY")
aa3 = "ALA CYS ASP GLU PHE GLY HIS ILE LYS LEU \
        MET ASN PRO GLN ARG SER THR VAL TRP TYR".split()
aa123 = dict(zip(aa1,aa3))

with open('mutations_1stn.txt', 'r') as lst:
    muts = lst.readlines()
    aa = [i[0] for i in muts]
    res = [int(i[1:-2]) for i in muts]

    for i, j in enumerate(aa):
        if j != seq[res[i]-1]:
            print(j, seq[res[i]-1], res[i], "not matching mutation description")

        else:
            print(j, seq[res[i]-1], res[i], "is correct")
